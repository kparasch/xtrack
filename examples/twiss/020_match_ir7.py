import xtrack as xt
import xpart as xp

# Load the line
line = xt.Line.from_json(
    '../../test_data/hllhc15_noerrors_nobb/line_w_knobs_and_particle.json')
line.particle_ref = xp.Particles(p0c=7e12, mass=xp.PROTON_MASS_EV)
collider = xt.Multiline(lines={'lhcb1': line})
collider.build_trackers()

tw_ref = collider.lhcb1.twiss()

ele_start_match = 's.ds.l7.b1'
ele_end_match = 'e.ds.r7.b1'
tw_init = tw_ref.get_twiss_init(ele_start_match)

betx_end_match = tw_ref['betx', ele_end_match]
bety_end_match = tw_ref['bety', ele_end_match]
alfx_end_match = tw_ref['alfx', ele_end_match]
alfy_end_match = tw_ref['alfy', ele_end_match]
dx_end_match = tw_ref['dx', ele_end_match]
dpx_end_match = tw_ref['dpx', ele_end_match]
mux_end_match = tw_ref['mux', ele_end_match]
muy_end_match = tw_ref['muy', ele_end_match]

betx_at_ip7 = tw_ref['betx', 'ip7']
bety_at_ip7 = tw_ref['bety', 'ip7']
alfx_at_ip7 = tw_ref['alfx', 'ip7']
alfy_at_ip7 = tw_ref['alfy', 'ip7']
dx_at_ip7 = tw_ref['dx', 'ip7']
dpx_at_ip7 = tw_ref['dpx', 'ip7']

scale = 23348.89927
scmin = 0.03*7000./line.vars['nrj']._value
qtlimitx28 = 1.0*225.0/scale
qtlimitx15 = 1.0*205.0/scale
qtlimit2 = 1.0*160.0/scale
qtlimit3 = 1.0*200.0/scale
qtlimit4 = 1.0*125.0/scale
qtlimit5 = 1.0*120.0/scale
qtlimit6 = 1.0*90.0/scale

# use,sequence=lhcb1,range=s.ds.l7.b1/e.ds.r7.b1;
# match,      sequence=lhcb1, beta0=bir7b1;
# weight,mux=10,muy=10;
# constraint, sequence=lhcb1, range=ip7,dx=dxip7b1,dpx =dpxip7b1;
# constraint, sequence=lhcb1, range=ip7,betx=betxip7b1,bety=betyip7b1;
# constraint, sequence=lhcb1, range=ip7,alfx=alfxip7b1,alfy=alfyip7b1;
# constraint, sequence=lhcb1, range=e.ds.r7.b1,alfx=eir7b1->alfx,alfy=eir7b1->alfy;
# constraint, sequence=lhcb1, range=e.ds.r7.b1,betx=eir7b1->betx,bety=eir7b1->bety;
# constraint, sequence=lhcb1, range=e.ds.r7.b1,dx=eir7b1->dx,dpx=eir7b1->dpx;
# constraint, sequence=lhcb1, range=e.ds.r7.b1,   mux=muxip7b1+eir7b1->mux;
# constraint, sequence=lhcb1, range=e.ds.r7.b1,   muy=muyip7b1+eir7b1->muy;
# if(match_on_aperture==1){
# constraint, sequence=lhcb1,range=MQ.11l7.b1, bety<180.49-0.33;
# constraint, sequence=lhcb1,range=MQ.9l7.b1, bety<174.5;
# constraint, sequence=lhcb1,range=MQ.8r7.b1, bety<176.92;
# constraint, sequence=lhcb1,range=MQ.10r7.b1, bety<179;
# };
# vary, name=kqt13.l7b1,  step=1.0E-9, lower=-qtlimit5, upper=qtlimit5;
# vary, name=kqt12.l7b1,  step=1.0E-9, lower=-qtlimit5, upper=qtlimit5;
# vary, name=kqtl11.l7b1, step=1.0E-9, lower=-qtlimit4*300./550., upper=qtlimit4*300./550.;
# vary, name=kqtl10.l7b1, step=1.0E-9, lower=-qtlimit4*500./550., upper=qtlimit4*500./550.;
# vary, name=kqtl9.l7b1,  step=1.0E-9, lower=-qtlimit4*400./550., upper=qtlimit4*400./550.;
# vary, name=kqtl8.l7b1,  step=1.0E-9, lower=-qtlimit4*300./550., upper=qtlimit4*300./550.;
# vary, name=kqtl7.l7b1,  step=1.0E-9, lower=-qtlimit4, upper=qtlimit4;
# vary, name=kq6.l7b1,    step=1.0E-9, lower=-qtlimit6, upper=qtlimit6;
# vary, name=kq6.r7b1,    step=1.0E-9, lower=-qtlimit6, upper=qtlimit6;
# vary, name=kqtl7.r7b1,  step=1.0E-9, lower=-qtlimit4, upper=qtlimit4;
# vary, name=kqtl8.r7b1,  step=1.0E-9, lower=-qtlimit4*550./550., upper=qtlimit4*550./550.;
# vary, name=kqtl9.r7b1,  step=1.0E-9, lower=-qtlimit4*500./550., upper=qtlimit4*500./550.;
# vary, name=kqtl10.r7b1, step=1.0E-9, lower=-qtlimit4, upper=qtlimit4;
# vary, name=kqtl11.r7b1, step=1.0E-9, lower=-qtlimit4, upper=qtlimit4;
# vary, name=kqt12.r7b1,  step=1.0E-9, lower=-qtlimit5, upper=qtlimit5;
# vary, name=kqt13.r7b1,  step=1.0E-9, lower=-qtlimit5, upper=qtlimit5;
# jacobian,calls=jac_calls, tolerance=jac_tol, bisec=jac_bisec;
# !simplex,  calls=15, tolerance=jac_tol;-
# !lmdif,calls=200,tolerance=1.e-21;
# endmatch;
