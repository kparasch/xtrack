# copyright ############################### #
# This file is part of the Xtrack Package.  #
# Copyright (c) CERN, 2021.                 #
# ######################################### #

from typing import Tuple

import xobjects as xo

from . import beam_elements
from .line import Line


class SerializationHeader(xo.Struct):
    """
    In a predetermined place in the buffer we have the metadata
    offset and the element type names. These have to be separate,
    because in order to rebuild TrackerData we need to first build
    ElementRefClass.
    """
    element_ref_data_offset = xo.UInt64
    reftype_names = xo.String[:]


class TrackerData:
    @staticmethod
    def generate_element_ref_data(element_ref_class) -> 'ElementRefData':
        class ElementRefData(xo.Struct):
            elements = element_ref_class[:]
            names = xo.String[:]

        return ElementRefData

    def __init__(
            self,
            line,
            element_classes=None,
            extra_element_classes=[],
            _context=None,
            _buffer=None,
            _offset=None,
    ):
        """
        Create an immutable line suitable for serialisation.

        :param xt.Line line: a line
        :param List[xo.Struct] element_classes: explicit list of classes of
            elements of the line; if `None`, will be inferred from list.
        :param List[xo.Struct] extra_element_classes: if `element_classes`
            is `None`, this list will be used to augment the inferred list
            of element classes.
        """
        self.line = line

        if _buffer is None:
            common_buffer = self.common_buffer_for_elements()
            if common_buffer is not None and _context in [common_buffer.context, None]:
                _buffer = common_buffer
            _buffer = _buffer or xo.get_a_buffer(context=_context, size=64)

        num_elements = len(line.element_names)

        if not element_classes:
            element_classes = set(ee._XoStruct for ee in line.elements)
            element_classes |= set(extra_element_classes)
            element_classes = sorted(element_classes, key=lambda cc: cc.__name__)
        self.element_classes = element_classes

        class ElementRefClass(xo.UnionRef):
            _reftypes = self.element_classes

        # freeze line
        line.element_names = tuple(line.element_names)
        self.element_s_locations = tuple(line.get_s_elements())
        self._ElementRefClass = ElementRefClass
        self._element_ref_data = self.move_elements_and_build_ref_data(_buffer)

    def common_buffer_for_elements(self):
        """If all `self.line` elements are in the same buffer,
        returns said buffer, otherwise returns `None`."""
        common_buffer = None
        for ee in self.line.elements:
            if hasattr(ee, '_buffer'):
                if common_buffer is None:
                    common_buffer = ee._buffer

                if ee._buffer is not common_buffer:
                    return None

        return common_buffer

    def to_binary(self, buffer=None) -> Tuple[xo.context.XBuffer, int]:
        """
        Return a buffer containing a binary representation of the LineFrozen,
        together with the offset to the header in the buffer.
        These two are sufficient for recreating the line.
        """
        _element_ref_data = self._element_ref_data
        if not buffer:
            buffer = _element_ref_data._buffer

        if buffer is not _element_ref_data._buffer:
            _element_ref_data = self.move_elements_and_build_ref_data(buffer)

        header = self.build_header(
            buffer=buffer,
            element_ref_data_offset=_element_ref_data._offset,
        )

        return buffer, header._offset

    def build_header(self, buffer, element_ref_data_offset) -> SerializationHeader:
        """
        Build a serialization header in the buffer. This contains all
        the necessary for decoding the line metadata.
        """
        return SerializationHeader(
            element_ref_data_offset=element_ref_data_offset,
            reftype_names=[
                reftype._DressingClass.__name__
                for reftype in self._ElementRefClass._reftypes
            ],
            _buffer=buffer,
        )

    def move_elements_and_build_ref_data(self, buffer):
        """
        Ensure all the elements of the line are in the buffer (which will be
        created if `buffer` is equal to `None`), and write the line metadata
        to it. If the buffer is empty, the metadata will be at the beginning.
        Returns the metadata xobject.
        """
        element_refs_cls = self.generate_element_ref_data(self._ElementRefClass)

        element_ref_data = element_refs_cls(
            elements=len(self.line.elements),
            names=list(self.line.element_names),
            _buffer=buffer,
        )

        # Move all the elements into buffer, so they don't get duplicated.
        # We only do it now, as we need to make sure element_ref_data is already
        # allocated after reftype_names.
        moved_element_dict = {}
        for name, elem in self.line.element_dict.items():
            if elem._buffer is not buffer:
                elem.move(_buffer=buffer)
            moved_element_dict[name] = elem._xobject

        element_ref_data.elements = [
            moved_element_dict[name] for name in self.line.element_names
        ]

        return element_ref_data

    @classmethod
    def from_binary(
        cls,
        buffer: xo.context.XBuffer,
        header_offset: int,
        extra_element_classes=[],
    ) -> 'TrackerData':
        header = SerializationHeader._from_buffer(
            buffer=buffer,
            offset=header_offset,
        )

        extra_classes_dict = {
            elem_cls.__name__: elem_cls
            for elem_cls in extra_element_classes
        }

        element_hybrid_classes = []
        for reftype in header.reftype_names:
            if reftype in extra_classes_dict:
                element_hybrid_classes.append(extra_classes_dict[reftype])
            elif hasattr(beam_elements, reftype):
                element_hybrid_classes.append(getattr(beam_elements, reftype))
            else:
                ValueError(f"Cannot find the type `{reftype}`")

        # With the reftypes loaded we can create our classes
        element_classes = [elem._XoStruct for elem in element_hybrid_classes]

        class ElementRefClass(xo.UnionRef):
            _reftypes = element_classes

        # We can now load the line from the buffer
        element_refs_cls = cls.generate_element_ref_data(ElementRefClass)
        element_ref_data = element_refs_cls._from_buffer(
            buffer=buffer,
            offset=int(header.element_ref_data_offset)
        )

        # Recreate and redress line elements
        hybrid_cls_for_xstruct = {
            elem._XoStruct: elem for elem in element_hybrid_classes
        }

        element_dict = {}
        for ii, elem in enumerate(element_ref_data.elements):
            name = element_ref_data.names[ii]
            if name in element_dict:
                continue

            hybrid_cls = hybrid_cls_for_xstruct[elem.__class__]
            element_dict[name] = hybrid_cls(_xobject=elem, _buffer=buffer)

        line = Line(
            elements=element_dict,
            element_names=element_ref_data.names,
        )
        tracker_data = TrackerData(line=line, element_classes=element_classes)
        tracker_data._ElementRefClass = ElementRefClass

        return tracker_data

    @property
    def elements(self):
        return self.line.elements

    @property
    def element_names(self):
        return self.line.element_names

    @property
    def _buffer(self):
        return self._element_ref_data._buffer

    @property
    def _offset(self):
        return self._element_ref_data._offset

    @property
    def _context(self):
        return self._element_ref_data._context