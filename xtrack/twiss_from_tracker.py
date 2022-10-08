# copyright ############################### #
# This file is part of the Xtrack Package.  #
# Copyright (c) CERN, 2021.                 #
# ######################################### #

import logging
from functools import partial
from operator import ne
import numpy as np

import xobjects as xo
import xpart as xp

from scipy.optimize import fsolve
from scipy.constants import c as clight

from . import linear_normal_form as lnf

import xtrack as xt # To avoid circular imports

DEFAULT_STEPS_R_MATRIX = {
    'dx':1e-7, 'dpx':1e-10,
    'dy':1e-7, 'dpy':1e-10,
    'dzeta':1e-6, 'ddelta':1e-7
}

log = logging.getLogger(__name__)


def twiss_from_tracker(tracker, particle_ref,
        particle_on_co=None, R_matrix=None, W_matrix=None,
        r_sigma=0.01, nemitt_x=1e-6, nemitt_y=2.5e-6,
        delta_disp=1e-5, delta_chrom = 1e-4,
        particle_co_guess=None, steps_r_matrix=None,
        co_search_settings=None, at_elements=None, at_s=None,
        continue_on_closed_orbit_error=False,
        values_at_element_exit=False,
        eneloss_and_damping=False,
        ele_start=0, ele_stop=None, twiss_init=None,
        skip_global_quantities=False,
        matrix_responsiveness_tol=lnf.DEFAULT_MATRIX_RESPONSIVENESS_TOL,
        matrix_stability_tol=lnf.DEFAULT_MATRIX_STABILITY_TOL,
        symplectify=False):


    if at_s is not None:
        # Get all arguments
        kwargs = locals().copy()
        if np.isscalar(at_s):
            at_s = [at_s]
        assert at_elements is None
        (auxtracker, names_inserted_markers
            ) = _build_auxiliary_tracker_with_extra_markers(
            tracker=tracker, at_s=at_s, marker_prefix='inserted_twiss_marker')
        kwargs.pop('tracker')
        kwargs.pop('at_s')
        kwargs.pop('at_elements')
        return twiss_from_tracker(tracker=auxtracker,
                        at_elements=names_inserted_markers, **kwargs)

    mux0 = 0
    muy0 = 0
    muzeta0 = 0
    if ele_start !=0 or ele_stop is not None:
        if ele_start !=0 and ele_stop is None:
            raise ValueError(
                'ele_stop must be specified if ele_start is not 0')
        elif ele_start == 0 and ele_stop is not None:
            raise ValueError(
                'ele_start must be specified if ele_stop is not None')
        assert twiss_init is not None, (
            'twiss_init must be provided if ele_start and ele_stop are used')

        if isinstance(ele_start, str):
            ele_start = tracker.line.element_names.index(ele_start)
        if isinstance(ele_stop, str):
            ele_stop = tracker.line.element_names.index(ele_stop)

        assert twiss_init.element_name == tracker.line.element_names[ele_start]
        particle_on_co = twiss_init.particle_on_co.copy()
        W_matrix = twiss_init.W_matrix
        skip_global_quantities = True
        mux0 = twiss_init.mux
        muy0 = twiss_init.muy
        muzeta0 = twiss_init.muzeta

    twiss_res = TwissTable()

    if particle_on_co is not None:
        part_on_co = particle_on_co
    else:
        part_on_co = tracker.find_closed_orbit(
                                particle_co_guess=particle_co_guess,
                                particle_ref=particle_ref,
                                co_search_settings=co_search_settings,
                                continue_on_closed_orbit_error=continue_on_closed_orbit_error)

    if W_matrix is not None:
        W = W_matrix
        RR = None
    else:
        if R_matrix is not None:
            RR = R_matrix
        else:
            RR = tracker.compute_one_turn_matrix_finite_differences(
                                                steps_r_matrix=steps_r_matrix,
                                                particle_on_co=part_on_co)

        W, Winv, Rot = lnf.compute_linear_normal_form(
                                RR, symplectify=symplectify,
                                responsiveness_tol=matrix_responsiveness_tol,
                                stability_tol=matrix_stability_tol)

    twiss_res_element_by_element = _propagate_optics(
        tracker=tracker,
        W_matrix=W,
        particle_on_co=part_on_co,
        mux0=mux0, muy0=muy0, muzeta0=muzeta0,
        ele_start=ele_start, ele_stop=ele_stop,
        nemitt_x=nemitt_x,
        nemitt_y=nemitt_y,
        r_sigma=r_sigma,
        delta_disp=delta_disp,
        matrix_responsiveness_tol=matrix_responsiveness_tol,
        matrix_stability_tol=matrix_stability_tol,
        symplectify=symplectify)
    twiss_res.update(twiss_res_element_by_element)
    twiss_res._ebe_fields = twiss_res_element_by_element.keys()


    if not skip_global_quantities:
        mux = twiss_res_element_by_element['mux']
        muy = twiss_res_element_by_element['muy']

        dqx, dqy = _compute_chromaticity(
            tracker=tracker,
            W_matrix=W,
            particle_on_co=part_on_co,
            delta_chrom=delta_chrom,
            tune_x=mux[-1], tune_y=muy[-1],
            nemitt_x=nemitt_x, nemitt_y=nemitt_y,
            matrix_responsiveness_tol=matrix_responsiveness_tol,
            matrix_stability_tol=matrix_stability_tol,
            symplectify=symplectify, steps_r_matrix=steps_r_matrix)

        dzeta = twiss_res_element_by_element['dzeta']
        qs = np.abs(twiss_res_element_by_element['muzeta'][-1])
        eta = -dzeta[-1]/tracker.line.get_length()
        alpha = eta + 1/part_on_co._xobject.gamma0[0]**2

        beta0 = part_on_co._xobject.beta0[0]
        circumference = tracker.line.get_length()
        T_rev = circumference/clight/beta0
        betz0 = W[4, 4]**2 + W[4, 5]**2
        ptau_co = twiss_res_element_by_element['ptau']

        twiss_res.update({
            'qx': mux[-1], 'qy': muy[-1], 'qs': qs, 'dqx': dqx, 'dqy': dqy,
            'slip_factor': eta, 'momentum_compaction_factor': alpha, 'betz0': betz0,
            'circumference': circumference, 'T_rev': T_rev,
            'particle_on_co':part_on_co.copy(_context=xo.context_default)
        })
        twiss_res['particle_on_co']._fsolve_info = part_on_co._fsolve_info
        twiss_res['R_matrix'] = RR

        if eneloss_and_damping:
            assert RR is not None
            eneloss_damp_res = _compute_eneloss_and_damping_rates(
                particle_on_co=part_on_co, R_matrix=RR, ptau_co=ptau_co, T_rev=T_rev)
            twiss_res.update(eneloss_damp_res)

    if values_at_element_exit:
        for nn, vv in twiss_res_element_by_element.items():
            twiss_res[nn] = vv[1:]

    if at_elements is not None:
        twiss_res._keep_only_elements(at_elements)

    return twiss_res

def _one_turn_map(p, particle_ref, tracker, delta_zeta):
    part = particle_ref.copy()
    part.x = p[0]
    part.px = p[1]
    part.y = p[2]
    part.py = p[3]
    part.zeta = p[4] + delta_zeta
    part.delta = p[5]

    tracker.track(part)
    p_res = np.array([
           part._xobject.x[0],
           part._xobject.px[0],
           part._xobject.y[0],
           part._xobject.py[0],
           part._xobject.zeta[0],
           part._xobject.delta[0]])
    return p_res

def _propagate_optics(tracker, W_matrix, particle_on_co,
                      mux0, muy0, muzeta0,
                      ele_start, ele_stop,
                      nemitt_x, nemitt_y, r_sigma, delta_disp,
                      matrix_responsiveness_tol, matrix_stability_tol,
                      symplectify):

    ctx2np = tracker._context.nparray_from_context_array

    gemitt_x = nemitt_x/particle_on_co._xobject.beta0[0]/particle_on_co._xobject.gamma0[0]
    gemitt_y = nemitt_y/particle_on_co._xobject.beta0[0]/particle_on_co._xobject.gamma0[0]
    scale_transverse_x = np.sqrt(gemitt_x)*r_sigma
    scale_transverse_y = np.sqrt(gemitt_y)*r_sigma
    scale_longitudinal = delta_disp
    scale_eigen = min(scale_transverse_x, scale_transverse_y, scale_longitudinal)


    context = tracker._context
    part_for_twiss = xp.build_particles(_context=context,
                        particle_ref=particle_on_co, mode='shift',
                        x=  list(W_matrix[0, :] * scale_eigen) + [0],
                        px= list(W_matrix[1, :] * scale_eigen) + [0],
                        y=  list(W_matrix[2, :] * scale_eigen) + [0],
                        py= list(W_matrix[3, :] * scale_eigen) + [0],
                        zeta = list(W_matrix[4, :] * scale_eigen) + [0],
                        delta = list(W_matrix[5, :] * scale_eigen) + [0],
                        )

    part_disp = xp.build_particles(
        _context=context,
        x_norm=0,
        zeta=particle_on_co._xobject.zeta[0],
        delta=np.array([-delta_disp, +delta_disp])+particle_on_co._xobject.delta[0],
        particle_on_co=particle_on_co,
        scale_with_transverse_norm_emitt=(nemitt_x, nemitt_y),
        W_matrix=W_matrix,
        matrix_responsiveness_tol=matrix_responsiveness_tol,
        matrix_stability_tol=matrix_stability_tol,
        symplectify=symplectify)

    part_for_twiss = xp.Particles.merge([part_for_twiss, part_disp])
    part_for_twiss.s = particle_on_co.s[0]
    part_for_twiss.at_element = particle_on_co.at_element[0]
    i_start = part_for_twiss.at_element[0]

    assert np.all(ctx2np(part_for_twiss.at_turn) == 0)
    tracker.track(part_for_twiss, turn_by_turn_monitor='ONE_TURN_EBE',
                  ele_start=ele_start, ele_stop=ele_stop)
    assert np.all(ctx2np(part_for_twiss.state) == 1), (
        'Some test particles were lost during twiss!')
    i_stop = part_for_twiss.at_element[0] + (
        part_for_twiss.at_turn[0] * len(tracker.line.element_names))

    x_co = tracker.record_last_track.x[6, i_start:i_stop+1].copy()
    y_co = tracker.record_last_track.y[6, i_start:i_stop+1].copy()
    px_co = tracker.record_last_track.px[6, i_start:i_stop+1].copy()
    py_co = tracker.record_last_track.py[6, i_start:i_stop+1].copy()
    zeta_co = tracker.record_last_track.zeta[6, i_start:i_stop+1].copy()
    delta_co = tracker.record_last_track.delta[6, i_start:i_stop+1].copy()
    ptau_co = tracker.record_last_track.ptau[6, i_start:i_stop+1].copy()
    s_co = tracker.record_last_track.s[6, i_start:i_stop+1].copy()

    x_disp_minus = tracker.record_last_track.x[7, i_start:i_stop+1].copy()
    y_disp_minus = tracker.record_last_track.y[7, i_start:i_stop+1].copy()
    zeta_disp_minus = tracker.record_last_track.zeta[7, i_start:i_stop+1].copy()
    px_disp_minus = tracker.record_last_track.px[7, i_start:i_stop+1].copy()
    py_disp_minus = tracker.record_last_track.py[7, i_start:i_stop+1].copy()
    delta_disp_minus = tracker.record_last_track.delta[7, i_start:i_stop+1].copy()

    x_disp_plus = tracker.record_last_track.x[8, i_start:i_stop+1].copy()
    y_disp_plus = tracker.record_last_track.y[8, i_start:i_stop+1].copy()
    zeta_disp_plus = tracker.record_last_track.zeta[8, i_start:i_stop+1].copy()
    px_disp_plus = tracker.record_last_track.px[8, i_start:i_stop+1].copy()
    py_disp_plus = tracker.record_last_track.py[8, i_start:i_stop+1].copy()
    delta_disp_plus = tracker.record_last_track.delta[8, i_start:i_stop+1].copy()

    dx = (x_disp_plus-x_disp_minus)/(delta_disp_plus - delta_disp_minus)
    dy = (y_disp_plus-y_disp_minus)/(delta_disp_plus - delta_disp_minus)
    dzeta = (zeta_disp_plus-zeta_disp_minus)/(delta_disp_plus - delta_disp_minus)
    dpx = (px_disp_plus-px_disp_minus)/(delta_disp_plus - delta_disp_minus)
    dpy = (py_disp_plus-py_disp_minus)/(delta_disp_plus - delta_disp_minus)

    Ws = np.zeros(shape=(len(s_co), 6, 6), dtype=np.float64)
    Ws[:, 0, :] = (tracker.record_last_track.x[:6, i_start:i_stop+1] - x_co).T / scale_eigen
    Ws[:, 1, :] = (tracker.record_last_track.px[:6, i_start:i_stop+1] - px_co).T / scale_eigen
    Ws[:, 2, :] = (tracker.record_last_track.y[:6, i_start:i_stop+1] - y_co).T / scale_eigen
    Ws[:, 3, :] = (tracker.record_last_track.py[:6, i_start:i_stop+1] - py_co).T / scale_eigen
    Ws[:, 4, :] = (tracker.record_last_track.zeta[:6, i_start:i_stop+1] - zeta_co).T / scale_eigen
    Ws[:, 5, :] = (tracker.record_last_track.ptau[:6, i_start:i_stop+1] - ptau_co).T / particle_on_co.beta0 / scale_eigen

    betx = Ws[:, 0, 0]**2 + Ws[:, 0, 1]**2
    bety = Ws[:, 2, 2]**2 + Ws[:, 2, 3]**2

    gamx = Ws[:, 1, 0]**2 + Ws[:, 1, 1]**2
    gamy = Ws[:, 3, 2]**2 + Ws[:, 3, 3]**2

    alfx = - Ws[:, 0, 0] * Ws[:, 1, 0] - Ws[:, 0, 1] * Ws[:, 1, 1]
    alfy = - Ws[:, 2, 2] * Ws[:, 3, 2] - Ws[:, 2, 3] * Ws[:, 3, 3]

    mux = np.unwrap(np.arctan2(Ws[:, 0, 1], Ws[:, 0, 0]))/2/np.pi
    muy = np.unwrap(np.arctan2(Ws[:, 2, 3], Ws[:, 2, 2]))/2/np.pi
    muzeta = np.unwrap(np.arctan2(Ws[:, 4, 5], Ws[:, 4, 4]))/2/np.pi

    mux = mux - mux[0] + mux0
    muy = muy - muy[0] + muy0
    muzeta = muzeta - muzeta[0] + muzeta0

    W_matrix = [Ws[ii, :, :] for ii in range(len(s_co))]

    twiss_res_element_by_element = {
        'name': tracker.line.element_names[i_start:i_stop] + ('_end_point',),
        's': s_co,
        'x': x_co,
        'px': px_co,
        'y': y_co,
        'py': py_co,
        'zeta': zeta_co,
        'delta': delta_co,
        'ptau': ptau_co,
        'betx': betx,
        'bety': bety,
        'alfx': alfx,
        'alfy': alfy,
        'gamx': gamx,
        'gamy': gamy,
        'dx': dx,
        'dpx': dpx,
        'dy': dy,
        'dzeta': dzeta,
        'dpy': dpy,
        'mux': mux,
        'muy': muy,
        'muzeta': muzeta,
        'W_matrix': W_matrix,
        #'delta_disp_minus': delta_disp_minus,  # for debug
        #'delta_disp_plus': delta_disp_plus,    # for debug
    }

    return twiss_res_element_by_element

def _compute_chromaticity(tracker, W_matrix, particle_on_co, delta_chrom,
                    tune_x, tune_y,
                    nemitt_x, nemitt_y, matrix_responsiveness_tol,
                    matrix_stability_tol, symplectify, steps_r_matrix
                    ):

    context = tracker._context

    part_chrom_plus = xp.build_particles(
                _context=context,
                x_norm=0,
                zeta=particle_on_co._xobject.zeta[0], delta=delta_chrom,
                particle_on_co=particle_on_co,
                scale_with_transverse_norm_emitt=(nemitt_x, nemitt_y),
                W_matrix=W_matrix,
                matrix_stability_tol=matrix_stability_tol,
                matrix_responsiveness_tol=matrix_responsiveness_tol,
                symplectify=symplectify)
    RR_chrom_plus = tracker.compute_one_turn_matrix_finite_differences(
                                            particle_on_co=part_chrom_plus.copy(),
                                            steps_r_matrix=steps_r_matrix)
    (WW_chrom_plus, WWinv_chrom_plus, Rot_chrom_plus
        ) = lnf.compute_linear_normal_form(RR_chrom_plus,
                                        responsiveness_tol=matrix_responsiveness_tol,
                                        stability_tol=matrix_stability_tol,
                                        symplectify=symplectify)
    qx_chrom_plus = np.angle(np.linalg.eig(Rot_chrom_plus)[0][0])/(2*np.pi)
    qy_chrom_plus = np.angle(np.linalg.eig(Rot_chrom_plus)[0][2])/(2*np.pi)

    part_chrom_minus = xp.build_particles(
                _context=context,
                x_norm=0,
                zeta=particle_on_co._xobject.zeta[0], delta=-delta_chrom,
                particle_on_co=particle_on_co,
                scale_with_transverse_norm_emitt=(nemitt_x, nemitt_y),
                W_matrix=W_matrix,
                matrix_responsiveness_tol=matrix_responsiveness_tol,
                matrix_stability_tol=matrix_stability_tol,
                symplectify=symplectify)
    RR_chrom_minus = tracker.compute_one_turn_matrix_finite_differences(
                                        particle_on_co=part_chrom_minus.copy(),
                                        steps_r_matrix=steps_r_matrix)
    (WW_chrom_minus, WWinv_chrom_minus, Rot_chrom_minus
        ) = lnf.compute_linear_normal_form(RR_chrom_minus,
                                          symplectify=symplectify,
                                          stability_tol=matrix_stability_tol,
                                          responsiveness_tol=matrix_responsiveness_tol)
    qx_chrom_minus = np.angle(np.linalg.eig(Rot_chrom_minus)[0][0])/(2*np.pi)
    qy_chrom_minus = np.angle(np.linalg.eig(Rot_chrom_minus)[0][2])/(2*np.pi)

    dist_from_half_integer_x = np.modf(tune_x)[0] - 0.5
    dist_from_half_integer_y = np.modf(tune_y)[0] - 0.5

    if np.abs(qx_chrom_plus - qx_chrom_minus) > np.abs(dist_from_half_integer_x):
        raise NotImplementedError(
                "Qx too close to half integer, impossible to evaluate Q'x")
    if np.abs(qy_chrom_plus - qy_chrom_minus) > np.abs(dist_from_half_integer_y):
        raise NotImplementedError(
                "Qy too close to half integer, impossible to evaluate Q'y")

    dqx = (qx_chrom_plus - qx_chrom_minus)/delta_chrom/2
    dqy = (qy_chrom_plus - qy_chrom_minus)/delta_chrom/2

    if dist_from_half_integer_x > 0:
        dqx = -dqx

    if dist_from_half_integer_y > 0:
        dqy = -dqy

    return dqx, dqy


def _compute_eneloss_and_damping_rates(particle_on_co, R_matrix, ptau_co, T_rev):
    diff_ptau = np.diff(ptau_co)
    eloss_turn = -sum(diff_ptau[diff_ptau<0]) * particle_on_co._xobject.p0c[0]

    # Get eigenvalues
    w0, v0 = np.linalg.eig(R_matrix)

    # Sort eigenvalues
    indx = [
        int(np.floor(np.argmax(np.abs(v0[:, 2*ii]))/2)) for ii in range(3)]
    eigenvals = np.array([w0[ii*2] for ii in indx])

    # Damping constants and partition numbers
    energy0 = particle_on_co.mass0 * particle_on_co._xobject.gamma0[0]
    damping_constants_turns = -np.log(np.abs(eigenvals))
    damping_constants_s = damping_constants_turns / T_rev
    partition_numbers = (
        damping_constants_turns* 2 * energy0/eloss_turn)

    eneloss_damp_res = {
        'eneloss_turn': eloss_turn,
        'damping_constants_turns': damping_constants_turns,
        'damping_constants_s':damping_constants_s,
        'partition_numbers': partition_numbers
    }

    return eneloss_damp_res

class ClosedOrbitSearchError(Exception):
    pass

def find_closed_orbit(tracker, particle_co_guess=None, particle_ref=None,
                      co_search_settings=None, delta_zeta=0,
                      continue_on_closed_orbit_error=False):

    if particle_co_guess is None:
        if particle_ref is None:
            if tracker.particle_ref is not None:
                particle_ref = tracker.particle_ref
            else:
                raise ValueError(
                    "Either `particle_co_guess` or `particle_ref` must be provided")

        particle_co_guess = particle_ref.copy()
        particle_co_guess.x = 0
        particle_co_guess.px = 0
        particle_co_guess.y = 0
        particle_co_guess.py = 0
        particle_co_guess.zeta = 0
        particle_co_guess.delta = 0
        particle_co_guess.s = 0
        particle_co_guess.at_element = 0
        particle_co_guess.at_turn = 0
    else:
        particle_ref = particle_co_guess

    if co_search_settings is None:
        co_search_settings = {}

    co_search_settings = co_search_settings.copy()
    if 'xtol' not in co_search_settings.keys():
        co_search_settings['xtol'] = 1e-6 # Relative error between calls

    particle_co_guess = particle_co_guess.copy(
                        _context=tracker._buffer.context)

    for shift_factor in [0, 1.]: # if not found at first attempt we shift slightly the starting point
        if shift_factor>0:
            log.warning('Need second attempt on closed orbit search')
        (res, infodict, ier, mesg
            ) = fsolve(lambda p: p - _one_turn_map(p, particle_co_guess, tracker, delta_zeta),
                x0=np.array([particle_co_guess._xobject.x[0] + shift_factor * 1e-5,
                            particle_co_guess._xobject.px[0] + shift_factor * 1e-7,
                            particle_co_guess._xobject.y[0] + shift_factor * 1e-5,
                            particle_co_guess._xobject.py[0] + shift_factor * 1e-7,
                            particle_co_guess._xobject.zeta[0] + shift_factor * 1e-4,
                            particle_co_guess._xobject.delta[0] + shift_factor * 1e-5]),
                full_output=True,
                **co_search_settings)
        fsolve_info = {
            'res': res, 'info': infodict, 'ier': ier, 'mesg': mesg}
        if ier == 1:
            break

    if ier != 1 and not(continue_on_closed_orbit_error):
        raise ClosedOrbitSearchError

    particle_on_co = particle_co_guess.copy()
    particle_on_co.x = res[0]
    particle_on_co.px = res[1]
    particle_on_co.y = res[2]
    particle_on_co.py = res[3]
    particle_on_co.zeta = res[4]
    particle_on_co.delta = res[5]

    particle_on_co._fsolve_info = fsolve_info

    return particle_on_co

def compute_one_turn_matrix_finite_differences(
        tracker, particle_on_co,
        steps_r_matrix=None):

    if steps_r_matrix is not None:
        steps_in = steps_r_matrix.copy()
        for nn in steps_in.keys():
            assert nn in DEFAULT_STEPS_R_MATRIX.keys(), (
                '`steps_r_matrix` can contain only ' +
                ' '.join(DEFAULT_STEPS_R_MATRIX.keys())
            )
        steps_r_matrix = DEFAULT_STEPS_R_MATRIX.copy()
        steps_r_matrix.update(steps_in)
    else:
        steps_r_matrix = DEFAULT_STEPS_R_MATRIX.copy()


    context = tracker._buffer.context

    particle_on_co = particle_on_co.copy(
                        _context=context)

    dx = steps_r_matrix["dx"]
    dpx = steps_r_matrix["dpx"]
    dy = steps_r_matrix["dy"]
    dpy = steps_r_matrix["dpy"]
    dzeta = steps_r_matrix["dzeta"]
    ddelta = steps_r_matrix["ddelta"]
    part_temp = xp.build_particles(_context=context,
            particle_ref=particle_on_co, mode='shift',
            x  =    [dx,  0., 0.,  0.,    0.,     0., -dx,   0.,  0.,   0.,     0.,      0.],
            px =    [0., dpx, 0.,  0.,    0.,     0.,  0., -dpx,  0.,   0.,     0.,      0.],
            y  =    [0.,  0., dy,  0.,    0.,     0.,  0.,   0., -dy,   0.,     0.,      0.],
            py =    [0.,  0., 0., dpy,    0.,     0.,  0.,   0.,  0., -dpy,     0.,      0.],
            zeta =  [0.,  0., 0.,  0., dzeta,     0.,  0.,   0.,  0.,   0., -dzeta,      0.],
            delta = [0.,  0., 0.,  0.,    0., ddelta,  0.,   0.,  0.,   0.,     0., -ddelta],
            )
    dpzeta = float(context.nparray_from_context_array(
        (part_temp.ptau[5] - part_temp.ptau[11])/2/part_temp.beta0[0]))
    if particle_on_co._xobject.at_element[0]>0:
        part_temp.s[:] = particle_on_co._xobject.s[0]
        part_temp.at_element[:] = particle_on_co._xobject.at_element[0]

    if particle_on_co._xobject.at_element[0]>0:
        i_start = particle_on_co._xobject.at_element[0]
        tracker.track(part_temp, ele_start=i_start)
        tracker.track(part_temp, num_elements=i_start)
    else:
        assert particle_on_co._xobject.at_element[0] == 0
        tracker.track(part_temp)

    temp_mat = np.zeros(shape=(6, 12), dtype=np.float64)
    temp_mat[0, :] = context.nparray_from_context_array(part_temp.x)
    temp_mat[1, :] = context.nparray_from_context_array(part_temp.px)
    temp_mat[2, :] = context.nparray_from_context_array(part_temp.y)
    temp_mat[3, :] = context.nparray_from_context_array(part_temp.py)
    temp_mat[4, :] = context.nparray_from_context_array(part_temp.zeta)
    temp_mat[5, :] = context.nparray_from_context_array(
                                part_temp.ptau/part_temp.beta0) # pzeta

    RR = np.zeros(shape=(6, 6), dtype=np.float64)

    for jj, dd in enumerate([dx, dpx, dy, dpy, dzeta, dpzeta]):
        RR[:, jj] = (temp_mat[:, jj] - temp_mat[:, jj+6])/(2*dd)

    return RR

def _behaves_like_drift(ee):
    return (hasattr(ee, 'behaves_like_drift') and ee.behaves_like_drift)


def _build_auxiliary_tracker_with_extra_markers(tracker, at_s, marker_prefix,
                                                algorithm='auto'):

    assert algorithm in ['auto', 'insert', 'regen_all_drift']
    if algorithm == 'auto':
        if len(at_s)<10:
            algorithm = 'insert'
        else:
            algorithm = 'regen_all_drifts'

    auxline = xt.Line(elements=list(tracker.line.elements).copy(),
                      element_names=list(tracker.line.element_names).copy())

    names_inserted_markers = []
    markers = []
    for ii, ss in enumerate(at_s):
        nn = marker_prefix + f'{ii}'
        names_inserted_markers.append(nn)
        markers.append(xt.Drift(length=0))

    if algorithm == 'insert':
        for nn, mm, ss in zip(names_inserted_markers, markers, at_s):
            auxline.insert_element(element=mm, name=nn, at_s=ss)
    elif algorithm == 'regen_all_drifts':
        s_elems = auxline.get_s_elements()
        s_keep = []
        enames_keep = []
        for ss, nn in zip(s_elems, auxline.element_names):
            if not (_behaves_like_drift(auxline[nn]) and np.abs(auxline[nn].length)>0):
                s_keep.append(ss)
                enames_keep.append(nn)
                assert not xt.line._is_thick(auxline[nn]) or auxline[nn].length == 0

        s_keep.extend(list(at_s))
        enames_keep.extend(names_inserted_markers)

        ind_sorted = np.argsort(s_keep)
        s_keep = np.take(s_keep, ind_sorted)
        enames_keep = np.take(enames_keep, ind_sorted)

        i_new_drift = 0
        new_enames = []
        new_ele_dict = auxline.element_dict.copy()
        new_ele_dict.update({nn: ee for nn, ee in zip(names_inserted_markers, markers)})
        s_curr = 0
        for ss, nn in zip(s_keep, enames_keep):
            if ss > s_curr + 1e-6:
                new_drift = xt.Drift(length=ss-s_curr)
                new_dname = f'_auxrift_{i_new_drift}'
                new_ele_dict[new_dname] = new_drift
                new_enames.append(new_dname)
                i_new_drift += 1
                s_curr = ss
            new_enames.append(nn)
        auxline = xt.Line(elements=new_ele_dict, element_names=new_enames)

    auxtracker = xt.Tracker(
        _buffer=tracker._buffer,
        line=auxline,
        track_kernel=tracker.track_kernel,
        element_classes=tracker.element_classes,
        particles_class=tracker.particles_class,
        skip_end_turn_actions=tracker.skip_end_turn_actions,
        reset_s_at_end_turn=tracker.reset_s_at_end_turn,
        particles_monitor_class=None,
        global_xy_limit=tracker.global_xy_limit,
        local_particle_src=tracker.local_particle_src
    )

    return auxtracker, names_inserted_markers



class TwissInit:
    def __init__(self, particle_on_co=None, W_matrix=None, element_name=None,
                 mux=0, muy=0, muzeta=0.):
        self.particle_on_co = particle_on_co
        self.W_matrix = W_matrix
        self.element_name = element_name
        self.mux = mux
        self.muy = muy
        self.muzeta = muzeta

class TwissTable(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.__dict__ = self

    def get_twiss_init(self, at_element):
        if isinstance(at_element, str):
            at_element = self.name.index(at_element)
        part = self.particle_on_co.copy()
        part.x[:] = self.x[at_element]
        part.px[:] = self.px[at_element]
        part.y[:] = self.y[at_element]
        part.py[:] = self.py[at_element]
        part.zeta[:] = self.zeta[at_element]
        part.ptau[:] = self.ptau[at_element]
        part.s[:] = self.s[at_element]
        part.at_element[:] = at_element

        W = self.W_matrix[at_element]

        return TwissInit(particle_on_co=part, W_matrix=W,
                        element_name=self.name[at_element],
                        mux=self.mux[at_element],
                        muy=self.muy[at_element],
                        muzeta=self.muzeta[at_element])

    def to_pandas(self, index=None):
        import pandas as pd

        df = pd.DataFrame(self)
        if index is not None:
            df.set_index(index, inplace=True)
        return df

    def get_summary(self):
        import pandas as pd
        dct = {k: v for k, v in self.items() if k not in self._ebe_fields}
        dct.pop('_ebe_fields')
        return pd.Series(dct)

    def get_betatron_sigmas(self, nemitt_x, nemitt_y):

        for ii in range(len(self.name)):
            v1 = Ws[ii, :, 0] + 1j * Ws[ii, :, 1]
            v2 = Ws[ii, :, 2] + 1j * Ws[ii, :, 3]

        Sigma_1 = np.matmul(v1, v1.T.conj(), axis=0)

        prrrr


    def mirror(self):
        new = TwissTable()
        for kk, vv in self.items():
            new[kk] = vv

        for kk in self._ebe_fields:
            if kk == 'name':
                new[kk] = new[kk][::-1]
            elif kk == 'W_matrix':
                continue
            else:
                new[kk] = new[kk][::-1].copy()

        new.s = new.circumference - new.s

        new.x = -new.x
        new.px = new.px # Dx/Ds
        new.y = new.y
        new.py = -new.py # Dy/Ds
        new.zeta = -new.zeta
        new.delta = new.delta
        new.ptau = new.ptau

        new.betx = new.betx
        new.bety = new.bety
        new.alfx = -new.alfx # Dpx/Dx
        new.alfy = -new.alfy # Dpy/Dy
        new.gamx = new.gamx
        new.gamy = new.gamy

        new.dx = -new.dx
        new.dpx = new.dpx
        new.dy = new.dy
        new.dpy = -new.dpy
        new.dzeta = -new.dzeta
        new.mux = new.qx - new.mux
        new.muy = new.qy - new.muy
        new.muzeta = new.qs - new.muzeta

        # To be checked
        new.W_matrix = np.array(new.W_matrix)
        new.W_matrix = new.W_matrix[::-1, :, :].copy()
        new.W_matrix[:, 0, :] = -new.W_matrix[:, 0, :]
        new.W_matrix[:, 1, :] = new.W_matrix[:, 1, :]
        new.W_matrix[:, 2, :] = new.W_matrix[:, 2, :]
        new.W_matrix[:, 3, :] = -new.W_matrix[:, 3, :]
        new.W_matrix[:, 4, :] = -new.W_matrix[:, 4, :]
        new.W_matrix[:, 5, :] = new.W_matrix[:, 5, :]
        new.W_matrix = [new.W_matrix[ii, :, :] for ii in range(len(new.x))]

        if hasattr(new, 'R_matrix'): new.R_matrix = None # To be implemented
        if hasattr(new, 'particle_on_co'): new.particle_on_co = None # To be implemented

        return new

    def _keep_only_elements(self, at_elements):
        enames = self.name
        if at_elements is not None:
            indx_twiss = []
            for nn in at_elements:
                if isinstance(nn, (int, np.integer)):
                    indx_twiss.append(int(nn))
                else:
                    assert nn in enames
                    indx_twiss.append(enames.index(nn))
            s_co = self['s']
            for kk, vv in self.items():
                if kk not in self._ebe_fields:
                    continue
                if hasattr(vv, '__len__') and len(vv) == len(s_co):
                    if isinstance(vv, np.ndarray):
                        self[kk] = vv[indx_twiss]
                    else:
                        self[kk] = [vv[ii] for ii in indx_twiss]

def _error_for_match(knob_values, vary, targets, tracker):
    for kk, vv in zip(vary, knob_values):
        tracker.vars[kk] = vv
    tw = tracker.twiss()
    res = []
    for tt in targets:
        if isinstance(tt[0], str):
            res.append(tw[tt[0]] - tt[1])
        else:
            res.append(tt[0](tw) - tt[1])
    return np.array(res)

def match_tracker(tracker, vary, targets):
    _err = partial(_error_for_match, vary=vary, targets=targets, tracker=tracker)
    x0 = [tracker.vars[vv]._value for vv in vary]
    (res, infodict, ier, mesg) = fsolve(_err, x0=x0, full_output=True)
    for kk, vv in zip(vary, res):
        tracker.vars[kk] = vv
    fsolve_info = {
            'res': res, 'info': infodict, 'ier': ier, 'mesg': mesg}
    return fsolve_info
