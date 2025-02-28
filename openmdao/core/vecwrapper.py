""" Class definition for VecWrapper"""

from collections import OrderedDict
import sys
import numpy
from numpy.linalg import norm
from six import iteritems
from six.moves import cStringIO

from openmdao.util.types import is_differentiable, int_types
from openmdao.util.strutil import get_common_ancestor

from openmdao.devtools.debug import *

class _flat_dict(object):
    """This is here to allow the user to use vec.flat['foo'] syntax instead
    of vec.flat('foo').
    """
    def __init__(self, vardict):
        self._dict = vardict

    def __getitem__(self, name):
        meta = self._dict[name]
        if meta.get('pass_by_obj'):
            raise ValueError("'%s' is a 'pass by object' variable. Flat value not found." % name)
        return self._dict[name]['val']


class _ByObjWrapper(object):
    """
    We have to wrap byobj values in these in order to have param vec entries
    that are shared between parents and children all share the same object
    reference, so that when the internal val attribute is changed, all
    `VecWrapper`s that contain a reference to the wrapper will see the updated
    value.
    """
    def __init__(self, val):
        self.val = val

    def __repr__(self):
        return repr(self.val)


class VecWrapper(object):
    """
    A dict-like container of a collection of variables.

    Args
    ----
    pathname : str, optional
        the pathname of the containing `System`

    comm : an MPI communicator (real or fake)
        a communicator that can be used for distributed operations
        when running under MPI.  If not running under MPI, it is
        ignored

    Attributes
    ----------
    idx_arr_type : dtype, optional
        A dtype indicating how index arrays are to be represented.
        The value 'i' indicates an numpy integer array, other
        implementations, e.g., petsc, will define this differently.
    """

    idx_arr_type = 'i'

    def __init__(self, pathname='', comm=None):
        self.pathname = pathname
        self.comm = comm
        self.vec = None
        self._vardict = OrderedDict()
        self._slices = OrderedDict()

        # add a flat attribute that will have access method consistent
        # with non-flat access  (__getitem__)
        self.flat = _flat_dict(self._vardict)

        # Automatic unit conversion in target vectors
        self.deriv_units = False
        self.adj_accumulate_mode = False

    def metadata(self, name):
        """
        Returns the metadata for the named variable.

        Args
        ----
        name : str
            Name of variable to get the metadata for.

        Returns
        -------
        dict
            The metadata dict for the named variable.

        Raises
        -------
        KeyError
            If the named variable is not in this vector.
        """
        try:
            return self._vardict[name]
        except KeyError as error:
            msg  = "Variable '{name}' does not exist".format(name=name)
            raise KeyError(msg)

    def __getitem__(self, name):
        """
        Retrieve unflattened value of named var.

        Args
        ----
        name : str
            Name of variable to get the value for.

        Returns
        -------
            The unflattened value of the named variable.
        """
        meta = self.metadata(name)

        if meta.get('pass_by_obj'):
            return meta['val'].val

        unitconv = meta.get('unit_conv')
        shape = meta.get('shape')

        # For dparam vector, getitem is disabled in adjoint mode.
        if self.adj_accumulate_mode == True:
            return numpy.zeros((shape))

        # Convert units
        elif unitconv:
            scale, offset = unitconv

            # Gradient is just the scale
            if self.deriv_units:
                offset = 0.0

            # if shape is 1, it's a float
            if shape == 1:
                return scale*(meta['val'][0] + offset)
            else:
                return scale*(meta['val'].reshape(shape) + offset)

        else:
            # if shape is 1, it's a float
            if shape == 1:
                return meta['val'][0]
            else:
                return meta['val'].reshape(shape)

    def __setitem__(self, name, value):
        """
        Set the value of the named variable.

        Args
        ----
        name : str
            Name of variable to get the value for.

        value :
            The unflattened value of the named variable.
        """
        meta = self.metadata(name)

        if meta.get('pass_by_obj'):
            meta['val'].val = value
            return

        unitconv = meta.get('unit_conv')

        # For dparam vector in adjoint mode, assignement behaves as +=.
        if self.adj_accumulate_mode is True:
            if self.deriv_units and unitconv:
                scale, offset = unitconv

                if isinstance(value, numpy.ndarray):
                    meta['val'][:] += scale*value.flat[:]
                else:
                    meta['val'][0] += scale*value

            else:
                if isinstance(value, numpy.ndarray):
                    meta['val'][:] += value.flat[:]
                else:
                    meta['val'][0] += value

        # Convert Units
        else:
            if self.deriv_units and unitconv:
                scale, offset = unitconv

                if isinstance(value, numpy.ndarray):
                    meta['val'][:] = scale*value.flat[:]
                else:
                    meta['val'][0] = scale*value

            else:
                if isinstance(value, numpy.ndarray):
                    meta['val'][:] = value.flat[:]
                else:
                    meta['val'][0] = value

    def __len__(self):
        """
        Returns
        -------
            The number of keys (variables) in this vector.
        """
        return len(self._vardict)

    def __contains__(self, key):
        """
        Returns
        -------
            A boolean indicating if the given key (variable name) is in this vector.
        """

        return key in self._vardict

    def __iter__(self):
        """
        Returns
        -------
            A dictionary iterator over the items in _vardict.
        """
        return self._vardict.__iter__()

    def keys(self):
        """
        Returns
        -------
        list or KeyView (python 3)
            the keys (variable names) in this vector.
        """
        return self._vardict.keys()

    def items(self):
        """
        Returns
        -------
        iterator
            Iterator returning the name and metadata dict for each variable.
        """
        return iteritems(self._vardict)

    def values(self):
        """
        Returns
        -------
        iterator
            Iterator returning a metadata dict for each variable.
        """
        for meta in self._vardict.values():
            yield meta

    def get_local_idxs(self, name, idx_dict):
        """
        Returns all of the indices for the named variable in this vector.

        Args
        ----
        name : str
            Name of variable to get the indices for.

        Returns
        -------
        size
            The size of the named variable

        ndarray
            Index array containing all local indices for the named variable.
        """
        # TODO: add support for returning slice objects

        meta = self._vardict[name]
        if meta.get('pass_by_obj'):
            raise RuntimeError("No vector indices can be provided "
                               "for 'pass by object' variable '%s'" % name)

        if name not in self._slices:
            return meta['size'], self.make_idx_array(0, 0)

        start, end = self._slices[name]
        if name in idx_dict:
            idxs = self.to_idx_array(idx_dict[name]) + start
            if idxs.size > (end-start) or max(idxs) >= end:
                raise RuntimeError("Indices of interest specified for '%s'"
                                   "are too large" % name)
            return idxs.size, idxs
        else:
            return meta['size'], self.make_idx_array(start, end)

    def norm(self):
        """
        Calculates the norm of this vector.

        Returns
        -------
        float
            Norm of our internal vector.
        """
        return norm(self.vec)

    def get_view(self, sys_pathname, comm, varmap, relevance, var_of_interest):
        """
        Return a new `VecWrapper` that is a view into this one.

        Args
        ----
        sys_pathname : str
            pathname of the system for which the view is being created

        comm : an MPI communicator (real or fake)
            A communicator that is used in the creation of the view.

        varmap : dict
            Mapping of variable names in the old `VecWrapper` to the names
            they will have in the new `VecWrapper`.

        Returns
        -------
        `VecWrapper`
            A new `VecWrapper` that is a view into this one.
        """
        view = self.__class__(sys_pathname, comm)
        view_size = 0

        start = -1
        for name, meta in self.items():
            if name in varmap:
                view._vardict[varmap[name]] = self._vardict[name]
                if not meta.get('pass_by_obj') and not meta.get('remote'):
                    pstart, pend = self._slices[name]
                    if start == -1:
                        start = pstart
                        end = pend
                    else:
                        assert pstart == end, \
                               "%s not contiguous in block containing %s" % \
                               (name, varmap.keys())
                    end = pend
                    view._slices[varmap[name]] = (view_size, view_size + meta['size'])
                    view_size += meta['size']

        if start == -1: # no items found
            view.vec = self.vec[0:0]
        else:
            view.vec = self.vec[start:end]

        return view

    def make_idx_array(self, start, end):
        """
        Return an index vector of the right int type for
        the current implementation.

        Args
        ----
        start : int
            The starting index.

        end : int
            The ending index.

        Returns
        -------
        ndarray of idx_arr_type
            index array containing all indices from start up to but
            not including end
        """
        return numpy.arange(start, end, dtype=self.idx_arr_type)

    def to_idx_array(self, indices):
        """
        Given some iterator of indices, return an index array of the
        right int type for the current implementation.

        Args
        ----
        indices : iterator of ints
            An iterator of indices.

        Returns
        -------
        ndarray of idx_arr_type
            Index array containing all of the given indices.

        """
        return numpy.array(indices, dtype=self.idx_arr_type)

    def merge_idxs(self, src_idxs, tgt_idxs):
        """
        Return source and target index arrays, built up from
        smaller index arrays and combined in order of ascending source
        index (to allow us to convert src indices to a slice in some cases).

        Args
        ----
        src_idxs : array
            Source indices.

        tgt_idxs : array
            Target indices.

        Returns
        -------
        ndarray of idx_arr_type
            Index array containing all of the merged indices.

        """
        assert(len(src_idxs) == len(tgt_idxs))

        # filter out any zero length idx array entries
        src_idxs = [i for i in src_idxs if len(i)]
        tgt_idxs = [i for i in tgt_idxs if len(i)]

        if len(src_idxs) == 0:
            return self.make_idx_array(0, 0), self.make_idx_array(0,0)

        src_tups = list(enumerate(src_idxs))

        src_sorted = sorted(src_tups, key=lambda x: x[1].min())

        new_src = [idxs for i, idxs in src_sorted]
        new_tgt = [tgt_idxs[i] for i,_ in src_sorted]

        return idx_merge(new_src), idx_merge(new_tgt)

    def get_promoted_varname(self, abs_name):
        """
        Returns the relative pathname for the given absolute variable
        pathname.

        Args
        ----
        abs_name : str
            Absolute pathname of a variable.

        Returns
        -------
        rel_name : str
            Relative name mapped to the given absolute pathname.
        """
        for rel_name, meta in self._vardict.items():
            if meta['pathname'] == abs_name:
                return rel_name
        raise RuntimeError("Relative name not found for variable '%s'" % abs_name)

    def get_states(self):
        """
        Returns
        -------
        list
            A list of names of state variables.
        """
        return [n for n,meta in self.items() if meta.get('state')]

    def get_vecvars(self):
        """
        Returns
        -------
            A list of names of variables found in our 'vec' array.
        """
        return [(n,meta) for n,meta in self.items() if not meta.get('pass_by_obj')]

    def get_byobjs(self):
        """
        Returns
        -------
        list
            A list of names of variables that are passed by object rather than
            through scattering entries from one array to another.
        """
        return [(n,meta) for n,meta  in self.items() if meta.get('pass_by_obj')]

    def _scoped_abs_name(self, name):
        """
        Args
        ----
        name : str
            The absolute pathname of a variable.

        Returns
        -------
        str
            The given name as seen from the 'scope' of the `System` that
            contains this `VecWrapper`.
        """
        if self.pathname:
            start = len(self.pathname)+1
        else:
            start = 0
        return name[start:]

    def dump(self, out_stream=sys.stdout):
        """
        Args
        ----
        out_stream : file_like
            Where to send human readable output. Default is sys.stdout. Set to
            None to return a str.
        """

        if out_stream is None:
            out_stream = cStringIO()
            return_str = True
        else:
            return_str = False

        lens = [len(n) for n in self.keys()]
        nwid = max(lens) if lens else 10
        vlens = [len(repr(self[v])) for v in self.keys()]
        vwid = max(vlens) if vlens else 1
        if len(self.get_vecvars()) != len(self.keys()): # we have some pass by obj
            defwid = 8
        else:
            defwid = 1
        slens = [len('[{0[0]}:{0[1]}]'.format(self._slices[v])) for v in self.keys()
                       if v in self._slices]+[defwid]
        swid = max(slens)

        for v, meta in self.items():
            if meta.get('pass_by_obj') or meta.get('remote'):
                continue
            if v in self._slices:
                uslice = '[{0[0]}:{0[1]}]'.format(self._slices[v])
            else:
                uslice = ''
            out_stream.write("{0:<{nwid}} {1:<{swid}} {2:>{vwid}}\n".format(v,
                                                                       uslice,
                                                                       repr(self[v]),
                                                                       nwid=nwid,
                                                                       swid=swid,
                                                                       vwid=vwid))

        for v, meta in self.items():
            if meta.get('pass_by_obj') and not meta.get('remote'):
                out_stream.write("{0:<{nwid}} {1:<{swid}} {2}\n".format(v, '(by obj)',
                                                                        repr(self[v]),
                                                                        nwid=nwid,
                                                                        swid=swid))
        if return_str:
            return out_stream.getvalue()

    def _set_adjoint_mode(self, mode=False):
        """ Turn on or off adjoint accumlate mode."""
        self.adj_accumulate_mode = mode



class SrcVecWrapper(VecWrapper):
    def setup(self, unknowns_dict, relevant_vars=None, store_byobjs=False):
        """
        Configure this vector to store a flattened array of the variables
        in unknowns. If store_byobjs is True, then 'pass by object' variables
        will also be stored.

        Args
        ----
        unknowns_dict : dict
            Dictionary of metadata for unknown variables collected from
            components.

        relevant_vars : iter of str
            Names of variables that are relevant a particular variable of
            interest.

        store_byobjs : bool, optional
            If True, then store 'pass by object' variables.
            By default only 'pass by vector' variables will be stored.

        """
        vec_size = 0
        for meta in unknowns_dict.values():
            promname = meta['promoted_name']
            if relevant_vars is None or meta['top_promoted_name'] in relevant_vars:
                vmeta = self._setup_var_meta(meta['pathname'], meta)
                if not vmeta.get('pass_by_obj') and not vmeta.get('remote'):
                    self._slices[promname] = (vec_size, vec_size + vmeta['size'])
                    vec_size += vmeta['size']

                self._vardict[promname] = vmeta

        self.vec = numpy.zeros(vec_size)

        # map slices to the array
        for name, meta in self.items():
            if not meta.get('remote') and not meta.get('pass_by_obj'):
                start, end = self._slices[name]
                meta['val'] = self.vec[start:end]

        # if store_byobjs is True, this is the unknowns vecwrapper,
        # so initialize all of the values from the unknowns dicts.
        if store_byobjs:
            for meta in unknowns_dict.values():
                if (relevant_vars is None or meta['pathname'] in relevant_vars) and not meta.get('remote'):
                    self[meta['promoted_name']] = meta['val']

    def _setup_var_meta(self, name, meta):
        """
        Populate the metadata dict for the named variable.

        Args
        ----
        name : str
           The name of the variable to add.

        meta : dict
            Starting metadata for the variable, collected from components
            in an earlier stage of setup.

        """
        vmeta = meta.copy()
        val = meta['val']
        if not is_differentiable(val) or meta.get('pass_by_obj'):
            vmeta['val'] = _ByObjWrapper(val)

        return vmeta

    def _get_flattened_sizes(self):
        """
        Collect all sizes of vars stored in our internal vector.

        Returns
        -------
        list of `OrderedDict`
            A one entry list containing an `OrderedDict` mapping var name to
            local size for 'pass by vector' variables.
        """
        sizes = OrderedDict([(n,m['size']) for n,m in self.items()
                 if not m.get('pass_by_obj') and not m.get('remote')])
        return [sizes]


class TgtVecWrapper(VecWrapper):
    def setup(self, parent_params_vec, params_dict, srcvec, my_params,
              connections, relevant_vars=None, store_byobjs=False):
        """
        Configure this vector to store a flattened array of the variables
        in params_dict. Variable shape and value are retrieved from srcvec.

        Args
        ----
        parent_params_vec : `VecWrapper` or None
            `VecWrapper` of parameters from the parent `System`.

        params_dict : `OrderedDict`
            Dictionary of parameter absolute name mapped to metadata dict.

        srcvec : `VecWrapper`
            Source `VecWrapper` corresponding to the target `VecWrapper` we're building.

        my_params : list of str
            A list of absolute names of parameters that the `VecWrapper` we're building
            will 'own'.

        connections : dict of str : str
            A dict of absolute target names mapped to the absolute name of their
            source variable.

        relevant_vars : iter of str
            Names of variables that are relevant a particular variable of
            interest.

        store_byobjs : bool, optional
            If True, store 'pass by object' variables in the `VecWrapper` we're building.
        """

        # dparams vector has some additional behavior
        if not store_byobjs:
            self.deriv_units = True

        vec_size = 0
        missing = []  # names of our params that we don't 'own'
        for meta in params_dict.values():
            pathname = meta['pathname']
            if relevant_vars is None or meta['top_promoted_name'] in relevant_vars:
                if pathname in my_params:
                    # if connected, get metadata from the source
                    src_pathname = connections.get(pathname)
                    if src_pathname is None:
                        raise RuntimeError("Parameter '%s' is not connected" % pathname)
                    src_rel_name = srcvec.get_promoted_varname(src_pathname)
                    src_meta = srcvec.metadata(src_rel_name)

                    vmeta = self._setup_var_meta(pathname, meta, vec_size,
                                                 src_meta, store_byobjs)
                    vmeta['owned'] = True

                    if not meta.get('remote'):
                        vec_size += vmeta['size']

                    self._vardict[self._scoped_abs_name(pathname)] = vmeta
                else:
                    if parent_params_vec is not None:
                        src = connections.get(pathname)
                        if src:
                            common = get_common_ancestor(src, pathname)
                            if common == self.pathname or (self.pathname+'.') not in common:
                                missing.append(meta)
        self.vec = numpy.zeros(vec_size)

        # map slices to the array
        for name, meta in self._vardict.items():
            if not meta.get('pass_by_obj') and not meta.get('remote'):
                start, end = self._slices[name]
                meta['val'] = self.vec[start:end]

        # fill entries for missing params with views from the parent
        for meta in missing:
            pathname = meta['pathname']
            newmeta = parent_params_vec._vardict[parent_params_vec._scoped_abs_name(pathname)]
            if newmeta['pathname'] == pathname:
                newmeta = newmeta.copy()
                newmeta['promoted_name'] = meta['promoted_name']
                newmeta['owned'] = False # mark this param as not 'owned' by this VW
                self._vardict[self._scoped_abs_name(pathname)] = newmeta

        # Finally, set up unit conversions, if any exist.
        for meta in params_dict.values():
            pathname = meta['pathname']
            if pathname in my_params and (relevant_vars is None or pathname in relevant_vars):
                unitconv = meta.get('unit_conv')
                if unitconv:
                    scale, offset = unitconv
                    if self.deriv_units:
                        offset = 0.0
                    self._vardict[self._scoped_abs_name(pathname)]['unit_conv'] = (scale, offset)

    def _setup_var_meta(self, pathname, meta, index, src_meta, store_byobjs):
        """
        Populate the metadata dict for the named variable.

        Args
        ----
        pathname : str
            Absolute name of the variable.

        meta : dict
            Metadata for the variable collected from components.

        index : int
            Index into the array where the variable value is to be stored
            (if variable is not 'pass by object').

        src_meta : dict
            Metadata for the source variable that this target variable is
            connected to.

        store_byobjs : bool, optional
            If True, store 'pass by object' variables in the `VecWrapper`
            we're building.
        """
        vmeta = meta.copy()
        if 'src_indices' not in vmeta:
            vmeta['size'] = src_meta['size']

        if src_meta.get('pass_by_obj'):
            if not meta.get('remote') and store_byobjs:
                vmeta['val'] = src_meta['val']
            vmeta['pass_by_obj'] = True
        elif not vmeta.get('remote'):
            self._slices[self._scoped_abs_name(pathname)] = (index, index + vmeta['size'])

        return vmeta

    def _add_unconnected_var(self, pathname, meta):
        """
        Add an entry to this vecwrapper for the given unconnected variable so the
        component can access its value through the vecwrapper.
        """
        vmeta = meta.copy()
        vmeta['pass_by_obj'] = True
        if 'val' in meta:
            val = meta['val']
        elif 'shape' in meta:
            val = numpy.zeros(shape)
        else:
            raise RuntimeError("Unconnected param '%s' has no specified val or shape" %
                               pathname)

        vmeta['val'] = _ByObjWrapper(val)
        self._vardict[self._scoped_abs_name(pathname)] = vmeta

    def _get_flattened_sizes(self):
        """
        Returns
        -------
        list of `OrderedDict`
            A one entry list of `OrderedDict` mapping names to local sizes of owned, local params
            in this `VecWrapper`.
        """
        psizes = OrderedDict()
        for name, m in self.items():
            if m.get('pass_by_obj') or not m.get('owned'):
                continue
            if m.get('remote'):
                psizes[name] = 0
            else:
                psizes[name] = m['size']

        return [psizes]


class PlaceholderVecWrapper(object):
    """
    A placeholder for a dict-like container of a collection of variables.

    Args
    ----
    name : str
        the name of the vector
    """

    def __init__(self, name=''):
        self.name = name

    def __getitem__(self, name):
        """
        Retrieve unflattened value of named var. Since this is just a
        placeholder, will raise an exception stating that setup() has
        not been called yet.

        Args
        ----
        name : str
            Name of variable to get the value for.

        Raises
        ------
        AttributeError
        """
        raise AttributeError("'%s' has not been initialized, "
                             "setup() must be called before '%s' can be accessed" %
                             (self.name, name))

    def __contains__(self, name):
        self.__getitem__(name)

    def __setitem__(self, name, value):
        """
        Set the value of the named variable. Since this is just a
        placeholder, will raise an exception stating that setup() has
        not been called yet.

        Args
        ----
        name : str
            Name of variable to get the value for.

        value :
            The unflattened value of the named variable.

        Raises
        ------
        AttributeError
        """
        raise AttributeError("'%s' has not been initialized, "
                             "setup() must be called before '%s' can be accessed" %
                             (self.name, name))
def idx_merge(idxs):
    """
    Combines a mixed iterator of int and iterator indices into an
    array of int indices.
    """
    if len(idxs) > 0:
        idxs = [i for i in idxs if isinstance(i, int_types) or
                len(i)>0]
        if len(idxs) > 0:
            if isinstance(idxs[0], int_types):
                return idxs
            else:
                return numpy.concatenate(idxs)
    return idxs
