""" Defines the base class for a Group in OpenMDAO."""

from __future__ import print_function

from collections import OrderedDict
import sys
from six import iteritems
from itertools import chain

# pylint: disable=E0611, F0401
import numpy as np

from openmdao.components.paramcomp import ParamComp
from openmdao.core.basicimpl import BasicImpl
from openmdao.core.component import Component
from openmdao.core.mpiwrap import MPI
from openmdao.core.system import System
from openmdao.solvers.run_once import RunOnce
from openmdao.solvers.scipy_gmres import ScipyGMRES
from openmdao.util.types import real_types
from openmdao.util.strutil import name_relative_to
#from openmdao.devtools.debug import debug

from openmdao.core.checks import ConnectError


class Group(System):
    """A system that contains other systems."""

    def __init__(self):
        super(Group, self).__init__()

        self._subsystems = OrderedDict()
        self._local_subsystems = OrderedDict()
        self._src = {}
        self._src_idxs = {}
        self._data_xfer = {}

        self._local_unknown_sizes = None
        self._local_param_sizes = None

        # These solvers are the default
        self.ln_solver = ScipyGMRES()
        self.nl_solver = RunOnce()

    def __getattr__(self, name):
        return self._subsystems[name]

    def __setitem__(self, name, val):
        """Sets the given value into the appropriate `VecWrapper`.

        Args
        ----
        name : str
             The name of the variable to set into the unknowns vector.
        """
        if self.is_active():
            try:
                self.unknowns[name] = val
            except KeyError:
                # look in params
                try:
                    subname, vname = name.rsplit('.', 1)
                    self._subsystem(subname).params[vname] = val
                except:
                    msg = "Can't find variable '%s' in unknowns or params " + \
                           "vectors in system '%s'"
                    raise KeyError(msg % (name, self.pathname))

    def __getitem__(self, name):
        """
        Retrieve unflattened value of named unknown or unconnected
        param variable.

        Args
        ----
        name : str
             The name of the variable to retrieve from the unknowns vector.

        Returns
        -------
        The unflattened value of the given variable.
        """

        # if setup has not been called, then there is no variable information to access
        if not self._local_unknown_sizes:
            raise RuntimeError('setup() must be called before variables can be accessed')

        # if system is not active, then it's not valid to access it's variables
        if not self.is_active():
            raise AttributeError("System '%s' is inactive, so can't access variable '%s'" %
                                 (self.pathname, name))

        try:
            return self.unknowns[name]
        except KeyError:
            subsys, subname = name.split('.', 1)
            try:
                return self._subsystems[subsys][subname]
            except:
                # look in params
                try:
                    subname, vname = name.rsplit('.', 1)
                    return self._subsystem(subname).params[vname]
                except:
                    msg = "Can't find variable '%s' in unknowns or params " + \
                           "vectors in system '%s'"
                    raise KeyError(msg % (name, self.pathname))

    def _subsystem(self, name):
        """
        Returns a reference to a named subsystem that is a direct or an indirect
        subsystem of the this system.  Raises an exception if the given name
        doesn't reference a subsystem.

        Args
        ----
        name : str
            Name of the subsystem to retrieve.

        Returns
        -------
        `System`
            A reference to the named subsystem.
        """
        s = self
        for part in name.split('.'):
            s = s._subsystems[part]
        return s

    def add(self, name, system, promotes=None):
        """Add a subsystem to this group, specifying its name and any variables
        that it promotes to the parent level.

        Args
        ----

        name : str
            The name by which the subsystem is to be known.

        system : `System`
            The subsystem to be added.

        promotes : tuple, optional
            The names of variables in the subsystem which are to be promoted.
        """
        if promotes is not None:
            system._promotes = promotes

        if name in self._subsystems.keys():
            msg = "Group '{gname}' already contains a subsystem with name"\
                            " '{cname}'.".format(gname=self.name, cname=name)
            raise RuntimeError(msg)
        self._subsystems[name] = system
        system.name = name
        return system

    def connect(self, source, targets, src_indices=None):
        """Connect the given source variable to the given target
        variable.

        Args
        ----

        source : source
            The name of the source variable.

        targets : str OR iterable
            The name of one or more target variables.
        """
        if isinstance(targets, str):
            targets = (targets,)

        for target in targets:
            self._src.setdefault(target, []).append(source)
            if src_indices is not None:
                self._src_idxs[target] = src_indices

    def subsystems(self, local=False, recurse=False, typ=System, include_self=False):
        """
        Args
        ----
        local : bool, optional
            If True, only return those `Components` that are local. Default is False.

        recurse : bool, optional
            If True, return all `Components` in the system tree, subject to
            the value of the local arg. Default is False.

        typ : type, optional
            If a class is specified here, only those subsystems that are instances
            of that type will be returned.  Default type is `System`.

        include_self : bool, optional
            If True, yield self before iterating over subsystems, assuming type
            of self is appropriate. Default is False.

        Returns
        -------
        iterator
            Iterator over subsystems.
        """
        if include_self and isinstance(self, typ):
            yield self

        subs = self._local_subsystems if local else self._subsystems

        for name, sub in subs.items():
            if isinstance(sub, typ):
                yield sub
            if recurse and isinstance(sub, Group):
                for s in sub.subsystems(local, recurse, typ):
                    yield s

    def subgroups(self, local=False, recurse=False, include_self=False):
        """
        Returns
        -------
        iterator
            Iterator over subgroups.
        """
        return self.subsystems(local=local, recurse=recurse, typ=Group,
                               include_self=include_self)

    def components(self, local=False, recurse=False, include_self=False):
        """
        Returns
        -------
        iterator
            Iterator over sub-`Components`.
        """
        return self.subsystems(local=local, recurse=recurse, typ=Component,
                               include_self=include_self)

    def _setup_paths(self, parent_path):
        """Set the absolute pathname of each `System` in the tree.

        Args
        ----
        parent_path : str
            The pathname of the parent `System`, which is to be prepended to the
            name of this child `System` and all subsystems.
        """
        super(Group, self)._setup_paths(parent_path)
        for sub in self.subsystems():
            sub._setup_paths(self.pathname)

    def _setup_variables(self):
        """
        Create dictionaries of metadata for parameters and for unknowns for
        this `Group` and stores them as attributes of the `Group`. The
        promoted name of subsystem variables with respect to this `Group`
        is included in the metadata.

        Returns
        -------
        tuple
            A dictionary of metadata for parameters and for unknowns
            for all subsystems.
        """
        self._params_dict = OrderedDict()
        self._unknowns_dict = OrderedDict()
        self._data_xfer = {}

        for sub in self.subsystems():
            subparams, subunknowns = sub._setup_variables()
            for p, meta in subparams.items():
                meta = meta.copy()
                meta['promoted_name'] = self._promoted_name(meta['promoted_name'], sub)
                if p in self._src_idxs:
                    meta['src_indices'] = self._src_idxs[p]
                self._params_dict[p] = meta

            for u, meta in subunknowns.items():
                meta = meta.copy()
                meta['promoted_name'] = self._promoted_name(meta['promoted_name'], sub)
                self._unknowns_dict[u] = meta

            # check for any promotes that didn't match a variable
            sub._check_promotes()

        return self._params_dict, self._unknowns_dict

    def _promoted_name(self, name, subsystem):
        """
        Returns
        -------
        str
            The promoted name of the given variable.
        """
        if subsystem.promoted(name):
            return name
        if len(subsystem.name) > 0:
            return '.'.join((subsystem.name, name))
        else:
            return name

    def _setup_communicators(self, comm):
        """
        Assign communicator to this `Group` and all of its subsystems.

        Args
        ----
        comm : an MPI communicator (real or fake)
            The communicator being offered by the parent system.
        """
        self._local_subsystems = OrderedDict()

        self.comm = comm

        for sub in self.subsystems():
            sub._setup_communicators(self.comm)
            if self.is_active() and sub.is_active():
                self._local_subsystems[sub.name] = sub

    def _setup_vectors(self, param_owners, parent=None,
                       relevance=None, top_unknowns=None, impl=BasicImpl):
        """Create `VecWrappers` for this `Group` and all below it in the
        `System` tree.

        Args
        ----
        param_owners : dict
            A dictionary mapping `System` pathnames to the pathnames of parameters
            they are reponsible for propagating.

        parent : `Group`, optional
            The `Group` that contains this `Group`, if any.

        relevance : `Relevance`
            An object that stores relevance information for each variable of interest.

        top_unknowns : `VecWrapper`, optional
            The `Problem` level unknowns `VecWrapper`.

        impl : an implementation factory, optional
            Specifies the factory object used to create `VecWrapper` and
            `DataXfer` objects.
        """
        self.params = self.unknowns = self.resids = None
        self.dumat, self.dpmat, self.drmat = {}, {}, {}
        self._local_unknown_sizes = None
        self._local_param_sizes = None
        self._owning_ranks = None

        if not self.is_active():
            return

        self._impl_factory = impl
        self._relevance = relevance

        my_params = param_owners.get(self.pathname, [])
        if parent is None:
            self._create_vecs(my_params, relevance, var_of_interest=None,
                              impl=impl)
            top_unknowns = self.unknowns
        else:
            self._create_views(top_unknowns, parent, my_params, relevance,
                               var_of_interest=None)

        self._local_unknown_sizes = self.unknowns._get_flattened_sizes()
        self._local_param_sizes = self.params._get_flattened_sizes()
        self._owning_ranks = self._get_owning_ranks()

        self._setup_data_transfer(my_params, relevance, None)

        # TODO: determine the size of the largest grouping of parallel subvecs, allocate
        #       an array of that size, and sub-allocate from that for all relevant subvecs
        #       We should never need more memory than the largest sized collection of parallel
        #       vecs.

        # create storage for the relevant vecwrappers,
        # keyed by variable_of_interest
        for group, vois in self._relevance.groups.items():
            if group is not None:
                for voi in vois:
                    if parent is None:
                        self._create_vecs(my_params, relevance, voi, impl)
                    else:
                        self._create_views(top_unknowns, parent, my_params,
                                           relevance, voi)

                    self._setup_data_transfer(my_params, relevance, voi)

        # convert any src_indices to index arrays
        for meta in self._params_dict.values():
            if 'src_indices' in meta:
                meta['src_indices'] = self.params.to_idx_array(meta['src_indices'])

        for sub in self.subsystems():
            sub._setup_vectors(param_owners, parent=self,
                               relevance=relevance, top_unknowns=top_unknowns)

        # now that all of the vectors and subvecs are allocated, calculate
        # and cache the ls_inputs.
        self._ls_inputs = {}
        for voi, vec in self.dumat.items():
            self._ls_inputs[voi] = self._all_params(voi)

    def _get_fd_params(self):
        """
        Get the list of parameters that are needed to perform a
        finite difference on this `Group`.

        Returns
        -------
        list of str
            List of names of params that have sources that are ParamComps
            or sources that are outside of this `Group` .
        """
        conns = self.connections
        mypath = self.pathname + '.' if self.pathname else ''

        params = []
        for tgt, src in conns.items():
            if tgt.startswith(mypath):
                # look up the Component that contains the source variable
                scname = src.rsplit('.', 1)[0]
                if scname.startswith(mypath):
                    src_comp = self._subsystem(scname[len(mypath):])
                    if isinstance(src_comp, ParamComp):
                        params.append(tgt[len(mypath):])
                else:
                    params.append(tgt[len(mypath):])

        return params

    def _get_fd_unknowns(self):
        """
        Get the list of unknowns that are needed to perform a
        finite difference on this `Group`.

        Returns
        -------
        list of str
            List of names of unknowns for this `Group` that don't come from a
            `ParamComp`.
        """
        mypath = self.pathname + '.' if self.pathname else ''
        fd_unknowns = []
        for name, meta in self.unknowns.items():
            # look up the subsystem containing the unknown
            sub = self._subsystem(meta['pathname'].rsplit('.', 1)[0][len(mypath):])
            if not isinstance(sub, ParamComp):
                fd_unknowns.append(name)

        return fd_unknowns

    def _get_explicit_connections(self):
        """
        Returns
        -------
        dict
            Explicit connections in this `Group`, represented as a mapping
            from the pathname of the target to the pathname of the source.
        """
        connections = {}
        for sub in self.subgroups():
            connections.update(sub._get_explicit_connections())

        for tgt, srcs in self._src.items():
            for src in srcs:
                try:
                    src_pathnames = get_absvarpathnames(src, self._unknowns_dict, 'unknowns')
                except KeyError as error:
                    try:
                        # if src is a param, it must use scoped absolute naming, so convert to top
                        # level absolute name for lookup in params_dict
                        s = self._get_var_pathname(src)
                        # verify that src is actually in self._params_dict
                        self._params_dict[s]
                        src_pathnames = [s]
                    except KeyError as error:
                        raise ConnectError.nonexistent_src_error(src, tgt)

                try:
                    for tgt_pathname in get_absvarpathnames(tgt, self._params_dict, 'params'):
                        connections.setdefault(tgt_pathname, []).extend(src_pathnames)
                except KeyError as error:
                    try:
                        get_absvarpathnames(tgt, self._unknowns_dict, 'unknowns')
                    except KeyError as error:
                        raise ConnectError.nonexistent_target_error(src, tgt)
                    else:
                        raise ConnectError.invalid_target_error(src, tgt)

        return connections

    def solve_nonlinear(self, params=None, unknowns=None, resids=None, metadata=None):
        """
        Solves the group using the slotted nl_solver.

        Args
        ----
        params : `VecWrapper`, optional
            `VecWrapper` containing parameters. (p)

        unknowns : `VecWrapper`, optional
            `VecWrapper` containing outputs and states. (u)

        resids : `VecWrapper`, optional
            `VecWrapper`  containing residuals. (r)

        metadata : dict, optional
            Dictionary containing execution metadata (e.g. iteration coordinate).
        """
        if self.is_active():
            params = params if params is not None else self.params
            unknowns = unknowns if unknowns is not None else self.unknowns
            resids = resids if resids is not None else self.resids

            self.nl_solver.solve(params, unknowns, resids, self, metadata)

    def children_solve_nonlinear(self, metadata):
        """
        Loops over our children systems and asks them to solve.

        Args
        ----
        metadata : dict
            Dictionary containing execution metadata (e.g. iteration coordinate).
        """

        # transfer data to each subsystem and then solve_nonlinear it
        for sub in self.subsystems():
            self._transfer_data(sub.name)
            if sub.is_active():
                if isinstance(sub, Component):
                    sub.solve_nonlinear(sub.params, sub.unknowns, sub.resids)
                else:
                    sub.solve_nonlinear(sub.params, sub.unknowns, sub.resids, metadata)

    def apply_nonlinear(self, params, unknowns, resids, metadata=None):
        """
        Evaluates the residuals of our children systems.

        Args
        ----
        params : `VecWrapper`
            `VecWrapper` containing parameters. (p)

        unknowns : `VecWrapper`
            `VecWrapper` containing outputs and states. (u)

        resids : `VecWrapper`
            `VecWrapper` containing residuals. (r)

        metadata : dict, optional
            Dictionary containing execution metadata (e.g. iteration coordinate).
        """
        if not self.is_active():
            return

        # transfer data to each subsystem and then apply_nonlinear to it
        for sub in self.subsystems():
            self._transfer_data(sub.name)
            if sub.is_active():
                if isinstance(sub, Component):
                    sub.apply_nonlinear(sub.params, sub.unknowns, sub.resids)
                else:
                    sub.apply_nonlinear(sub.params, sub.unknowns, sub.resids, metadata)

    def jacobian(self, params, unknowns, resids):
        """
        Linearize all our subsystems.

        Args
        ----
        params : `VecWrapper`
            `VecWrapper` containing parameters. (p)

        unknowns : `VecWrapper`
            `VecWrapper` containing outputs and states. (u)

        resids : `VecWrapper`
            `VecWrapper` containing residuals. (r)
        """

        for sub in self.subsystems(local=True):

            # Instigate finite difference on child if user requests.
            if sub.fd_options['force_fd'] == True:
                # Groups need total derivatives
                if isinstance(sub, Group):
                    total_derivs = True
                else:
                    total_derivs = False
                jacobian_cache = sub.fd_jacobian(sub.params, sub.unknowns,
                                                 sub.resids,
                                                 total_derivs=total_derivs)
            else:
                jacobian_cache = sub.jacobian(sub.params, sub.unknowns,
                                              sub.resids)

            # Cache the Jacobian for Components that aren't Paramcomps.
            # Also cache it for systems that are finite differenced.
            if (isinstance(sub, Component) or \
                                   sub.fd_options['force_fd'] == True) and \
                                   not isinstance(sub, ParamComp):
                sub._jacobian_cache = jacobian_cache

            # The user might submit a scalar Jacobian as a float.
            # It is really inconvenient if we don't allow it.
            if jacobian_cache is not None:
                for key, J in iteritems(jacobian_cache):
                    if isinstance(J, real_types):
                        jacobian_cache[key] = np.array([[J]])
                    shape = jacobian_cache[key].shape
                    if len(shape) < 2:
                        jacobian_cache[key] = jacobian_cache[key].reshape((shape[0], 1))

    def apply_linear(self, mode, ls_inputs=None, vois=[None]):
        """Calls apply_linear on our children. If our child is a `Component`,
        then we need to also take care of the additional 1.0 on the diagonal
        for explicit outputs.

        df = du - dGdp * dp or du = df and dp = -dGdp^T * df

        Args
        ----

        mode : string
            Derivative mode, can be 'fwd' or 'rev'.

        ls_inputs : dict
            We can only solve derivatives for the inputs the instigating
            system has access to.

        vois: list of strings
            List of all quantities of interest to key into the mats.
        """
        if not self.is_active():
            return

        if mode == 'fwd':
            self._transfer_data(deriv=True) # Full Scatter

        for sub in self.subsystems(local=True):
            # Components that are not paramcomps perform a matrix-vector
            # product on their variables. Any group where the user requests
            # a finite difference is also treated as a component.
            if (isinstance(sub, Component) or \
                             sub.fd_options['force_fd'] == True) and \
                             not isinstance(sub, ParamComp):
                self._sub_apply_linear_wrapper(sub, mode, vois, ls_inputs)

            # Groups and all other systems just call their own apply_linear.
            else:
                sub.apply_linear(mode, ls_inputs=ls_inputs, vois=vois)

        if mode == 'rev':
            self._transfer_data(mode='rev', deriv=True) # Full Scatter

    def _sub_apply_linear_wrapper(self, system, mode, vois, ls_inputs=None):
        """
        Calls apply_linear on any Component-like subsystem. This
        basically does two things: 1) multiplies the user Jacobian by -1, and
        2) puts a 1 on the diagonal for all explicit outputs.

        Args
        ----

        system : `System`
            Subsystem of interest, either a `Component` or a `Group` that is
            being finite differenced.

        mode : string
            Derivative mode, can be 'fwd' or 'rev'.

        vois: list of strings
            List of all quantities of interest to key into the mats.

        ls_inputs : dict
            We can only solve derivatives for the inputs the instigating
            system has access to.
        """

        for voi in vois:

            dresids = system.drmat[voi]
            dunknowns = system.dumat[voi]
            dparams = system.dpmat[voi]

            # Linear GS imposes a stricter requirement on whether or not to run.
            abs_inputs = {meta['pathname'] for meta in dparams.values()}

            # Forward Mode
            if mode == 'fwd':

                dresids.vec[:] = 0.0

                if ls_inputs[voi] is None or abs_inputs.intersection(ls_inputs[voi]):
                    if system.fd_options['force_fd'] == True:
                        system._apply_linear_jac(system.params, system.unknowns, dparams,
                                                 dunknowns, dresids, mode)
                    else:
                        system.apply_linear(system.params, system.unknowns, dparams,
                                            dunknowns, dresids, mode)
                dresids.vec *= -1.0

                for var, meta in dunknowns.items():
                    # Skip all states
                    if not meta.get('state'):
                        dresids[var] += dunknowns[var]

            # Adjoint Mode
            elif mode == 'rev':

                dparams.vec[:] = 0.0

                # Sign on the local Jacobian needs to be -1 before
                # we add in the fake residual. Since we can't modify
                # the 'du' vector at this point without stomping on the
                # previous component's contributions, we can multiply
                # our local 'arg' by -1, and then revert it afterwards.
                dresids.vec *= -1.0

                if ls_inputs[voi] is None or set(abs_inputs).intersection(ls_inputs[voi]):

                    try:
                        dparams._set_adjoint_mode(True)
                        if system.fd_options['force_fd'] == True:
                            system._apply_linear_jac(system.params,
                                                     system.unknowns, dparams,
                                                     dunknowns, dresids, mode)
                        else:
                            system.apply_linear(system.params, system.unknowns,
                                                dparams, dunknowns, dresids, mode)

                    finally:
                        dparams._set_adjoint_mode(False)

                dresids.vec *= -1.0

                for var, meta in dunknowns.items():
                    # Skip all states
                    if not meta.get('state'):
                        dunknowns[var] += dresids[var]

    def solve_linear(self, dumat, drmat, vois, mode=None):
        """
        Single linear solution applied to whatever input is sitting in
        the rhs vector.

        Args
        ----
        dumat : dict of `VecWrappers`
            In forward mode, each `VecWrapper` contains the incoming vector
            for the states. There is one vector per quantity of interest for
            this problem. In reverse mode, it contains the outgoing vector for
            the states. (du)

        drmat : `dict of VecWrappers`
            `VecWrapper` containing either the outgoing result in forward mode
            or the incoming vector in reverse mode. There is one vector per
            quantity of interest for this problem. (dr)

        vois: list of strings
            List of all quantities of interest to key into the mats.

        mode : string, optional
            Derivative mode, can be 'fwd' or 'rev', but generally should be
            called without mode so that the user can set the mode in this
            system's ln_solver.options.
        """
        if not self.is_active():
            return

        if mode is None:
            mode = self.fd_options['mode']

        if mode == 'fwd':
            sol_vec, rhs_vec = dumat, drmat
        else:
            sol_vec, rhs_vec = drmat, dumat

        # TODO: Need the norm. Loop over vois here.
        #if np.linalg.norm(rhs) < 1e-15:
        #    sol_vec.vec[:] = 0.0
        #    return

        # Solve Jacobian, df |-> du [fwd] or du |-> df [rev]
        rhs_buf = {}
        for voi in vois:
            rhs_buf[voi] = rhs_vec[voi].vec.copy()
        sol_buf = self.ln_solver.solve(rhs_buf, self, mode=mode)
        for voi in vois:
            sol_vec[voi].vec[:] = sol_buf[voi][:]

    def _all_params(self, voi=None):
        """ Returns the set of all parameters in this system and all subsystems.

        Args
        ----
        voi: string
            Variable of interest, default is None.
        """

        # TODO: clean this up
        ls_inputs = set(self.dpmat[voi].keys())
        abs_uvec = {meta['pathname'] for meta in self.dumat[voi].values()}

        for comp in self.components(local=True, recurse=True):
            for intinp_rel, meta in comp.dpmat[voi].items():
                intinp_abs = meta['pathname']
                src = self.connections.get(intinp_abs)

                if src in abs_uvec:
                    ls_inputs.add(intinp_abs)

        return ls_inputs

    def dump(self, nest=0, out_stream=sys.stdout, verbose=True, dvecs=False):
        """
        Writes a formated dump of the `System` tree to file.

        Args
        ----
        nest : int, optional
            Starting nesting level.  Defaults to 0.

        out_stream : file-like, optional
            Where output is written.  Defaults to sys.stdout.

        verbose : bool, optional
            If True (the default), output additional info beyond
            just the tree structure.

        dvecs : bool, optional
            If True, show contents of du and dp vectors instead of
            u and p (the default).
        """
        klass = self.__class__.__name__
        if dvecs:
            ulabel, plabel, uvecname, pvecname = 'du', 'dp', 'dunknowns', 'dparams'
        else:
            ulabel, plabel, uvecname, pvecname = 'u', 'p', 'unknowns', 'params'

        uvec = getattr(self, uvecname)
        pvec = getattr(self, pvecname)

        commsz = self.comm.size if hasattr(self.comm, 'size') else 0

        template = "%s %s '%s'    req: %s  usize:%d  psize:%d  commsize:%d\n"
        out_stream.write(template % (" "*nest,
                                     klass,
                                     self.name,
                                     self.get_req_procs(),
                                     uvec.vec.size,
                                     pvec.vec.size,
                                     commsz))

        vec_conns = dict(self._data_xfer[('', 'fwd', None)].vec_conns)
        byobj_conns = dict(self._data_xfer[('', 'fwd', None)].byobj_conns)

        # collect width info
        lens = [len(u)+sum(map(len, v)) for u, v in
                chain(vec_conns.items(), byobj_conns.items())]
        if lens:
            nwid = max(lens) + 9
        else:
            lens = [len(n) for n in uvec.keys()]
            nwid = max(lens) if lens else 12

        for v, meta in uvec.items():
            if verbose:
                if meta.get('pass_by_obj') or meta.get('remote'):
                    continue
                out_stream.write(" "*(nest+8))
                uslice = '{0}[{1[0]}:{1[1]}]'.format(ulabel, uvec._slices[v])
                pnames = [p for p, u in vec_conns.items() if u == v]

                if pnames:
                    if len(pnames) == 1:
                        pname = pnames[0]
                        pslice = pvec._slices.get(pname, (-1, -1))
                        pslice = '%d:%d' % (pslice[0], pslice[1])
                    else:
                        pslice = [('%d:%d' % pvec._slices.get(p, (-1, -1))) for p in pnames]
                        if len(pslice) > 1:
                            pslice = ','.join(pslice)
                        else:
                            pslice = pslice[0]

                    pslice = '{}[{}]'.format(plabel, pslice)

                    connstr = '%s -> %s' % (v, pnames)
                    template = "{0:<{nwid}} {1:<10} {2:<10} {3:>10}\n"
                    out_stream.write(template.format(connstr,
                                                     uslice,
                                                     pslice,
                                                     repr(uvec[v]),
                                                     nwid=nwid))
                else:
                    template = "{0:<{nwid}} {1:<21} {2:>10}\n"
                    out_stream.write(template.format(v,
                                                     uslice,
                                                     repr(uvec[v]),
                                                     nwid=nwid))

        if not dvecs:
            for dest, src in byobj_conns.items():
                out_stream.write(" "*(nest+8))
                connstr = '%s -> %s:' % (src, dest)
                template = "{0:<{nwid}} (by_obj)  ({1})\n"
                out_stream.write(template.format(connstr,
                                                 repr(uvec[src]),
                                                 nwid=nwid))

        nest += 3
        for sub in self.subsystems(local=True):
            sub.dump(nest, out_stream=out_stream, verbose=verbose, dvecs=dvecs)

        out_stream.flush()

    def get_req_procs(self):
        """
        Returns
        -------
        tuple
            A tuple of the form (min_procs, max_procs), indicating the min and max
            processors usable by this `Group`.
        """
        min_procs = 1
        max_procs = 1

        for sub in self.subsystems():
            sub_min, sub_max = sub.get_req_procs()
            min_procs = max(min_procs, sub_min)
            if max_procs is not None:
                if sub_max is None:
                    max_procs = None
                else:
                    max_procs = max(max_procs, sub_max)

        return (min_procs, max_procs)

    def _get_global_offset(self, name, var_rank, sizes_table, var_of_interest):
        """
        Args
        ----
        name : str
            The variable name.

        var_rank : int
            The rank the the offset is requested for.

        sizes_table : list of OrderDicts mappping var name to size.
            Size information for all vars in all ranks.

        var_of_interest : str
            Name of the current variable of interest, the key into the
            dumat,drmat, and dpmat dicts.

        Returns
        -------
        int
            The offset into the distributed vector for the named variable
            in the specified rank (process).
        """
        offset = 0
        rank = 0

        # first get the offset of the distributed storage for var_rank
        while rank < var_rank:
            for vname, size in sizes_table[rank].items():
                if self._relevance.is_relevant(var_of_interest, vname):
                    offset += size
            rank += 1

        # now, get the offset into the var_rank storage for the variable
        for vname, size in sizes_table[var_rank].items():
            if vname == name:
                break
            if self._relevance.is_relevant(var_of_interest, vname):
                offset += size

        return offset

    def _get_global_idxs(self, uname, pname, var_of_interest, mode):
        """
        Return the global indices into the distributed unknowns and params vector
        for the given unknown and param.  The given unknown and param have already
        been tested for relevance.

        Args
        ----
        uname : str
            Name of variable in the unknowns vector.

        pname : str
            Name of the variable in the params vector.

        var_of_interest : str or None
            Name of variable of interest used to determine relevance.

        mode : str
            Solution mode, either 'fwd' or 'rev'

        Returns
        -------
        tuple of (idx_array, idx_array)
            index array into the global unknowns vector and the corresponding
            index array into the global params vector.
        """
        umeta = self.unknowns.metadata(uname)
        pmeta = self.params.metadata(pname)

        # FIXME: if we switch to push scatters, this check will flip
        if (mode == 'fwd' and pmeta.get('remote')) or (mode == 'rev' and umeta.get('remote')):
            # just return empty index arrays for remote vars
            return self.params.make_idx_array(0, 0), self.params.make_idx_array(0, 0)

        if not self._relevance.is_relevant(var_of_interest, uname) or \
           not self._relevance.is_relevant(var_of_interest, pname):
            return self.params.make_idx_array(0, 0), self.params.make_idx_array(0, 0)

        if self.comm is None:
            iproc = 0
        else:
            iproc = self.comm.rank

        if 'src_indices' in pmeta:
            arg_idxs = self.params.to_idx_array(pmeta['src_indices'])
        else:
            arg_idxs = self.params.make_idx_array(0, pmeta['size'])

        if mode == 'fwd':
            var_rank = self._owning_ranks[uname]
        else:
            var_rank = iproc
        offset = self._get_global_offset(uname, var_rank, self._local_unknown_sizes,
                                         var_of_interest)
        src_idxs = arg_idxs + offset

        if mode == 'fwd':
            var_rank = iproc
        else:
            var_rank = self._owning_ranks[pname]
        tgt_start = self._get_global_offset(pname, var_rank, self._local_param_sizes,
                                            var_of_interest)
        tgt_idxs = tgt_start + self.params.make_idx_array(0, len(arg_idxs))

        return src_idxs, tgt_idxs

    def _setup_data_transfer(self, my_params, relevance, var_of_interest):
        """
        Create `DataXfer` objects to handle data transfer for all of the
        connections that involve parameters for which this `Group`
        is responsible.

        Args
        ----

        my_params : list
            List of pathnames for parameters that the `Group` is
            responsible for propagating.

        relevance : `Relevance`
            An object containing info about what variables are relevant
            to a variable of interest.

        var_of_interest : str or None
            The name of a variable of interest.

        """

        xfer_dict = {}
        for param, unknown in self.connections.items():
            if not (relevance.is_relevant(var_of_interest, param) or
                    relevance.is_relevant(var_of_interest, unknown)):
                continue

            if param in my_params:
                # remove our system pathname from the abs pathname of the param and
                # get the subsystem name from that

                tgt_sys = name_relative_to(self.pathname, param)
                src_sys = name_relative_to(self.pathname, unknown)

                for mode, sname in (('fwd', tgt_sys), ('rev', src_sys)):
                    src_idx_list, dest_idx_list, vec_conns, byobj_conns = \
                        xfer_dict.setdefault((sname, mode), ([], [], [], []))

                    urelname = self.unknowns.get_promoted_varname(unknown)
                    prelname = self.params.get_promoted_varname(param)

                    if self.unknowns.metadata(urelname).get('pass_by_obj'):
                        # rev is for derivs only, so no by_obj passing needed
                        if mode == 'fwd':
                            byobj_conns.append((prelname, urelname))
                    else: # pass by vector
                        sidxs, didxs = self._get_global_idxs(urelname, prelname,
                                                             var_of_interest, mode)
                        vec_conns.append((prelname, urelname))
                        src_idx_list.append(sidxs)
                        dest_idx_list.append(didxs)

        for (tgt_sys, mode), (srcs, tgts, vec_conns, byobj_conns) in xfer_dict.items():
            src_idxs, tgt_idxs = self.unknowns.merge_idxs(srcs, tgts)
            if vec_conns or byobj_conns:
                self._data_xfer[(tgt_sys, mode, var_of_interest)] = \
                    self._impl_factory.create_data_xfer(self.dumat[var_of_interest],
                                                        self.dpmat[var_of_interest],
                                                        src_idxs, tgt_idxs,
                                                        vec_conns, byobj_conns)

        # create a DataXfer object that combines all of the
        # individual subsystem src_idxs, tgt_idxs, and byobj_conns, so that a 'full'
        # scatter to all subsystems can be done at the same time.  Store that DataXfer
        # object under the name ''.

        for mode in ('fwd', 'rev'):
            full_srcs = []
            full_tgts = []
            full_flats = []
            full_byobjs = []
            for (tgt_sys, direction), (srcs, tgts, flats, byobjs) in xfer_dict.items():
                if mode == direction:
                    full_srcs.extend(srcs)
                    full_tgts.extend(tgts)
                    full_flats.extend(flats)
                    full_byobjs.extend(byobjs)

            src_idxs, tgt_idxs = self.unknowns.merge_idxs(full_srcs, full_tgts)
            self._data_xfer[('', mode, var_of_interest)] = \
                self._impl_factory.create_data_xfer(self.dumat[var_of_interest],
                                                    self.dpmat[var_of_interest],
                                                    src_idxs, tgt_idxs,
                                                    full_flats, full_byobjs)

    def _transfer_data(self, target_sys='', mode='fwd', deriv=False,
                       var_of_interest=None):
        """
        Transfer data to/from target_system depending on mode.

        Args
        ----

        target_sys : str, optional
            Name of the target `System`.  A name of '', the default, indicates that data
            should be transfered to all subsystems at once.

        mode : { 'fwd', 'rev' }, optional
            Specifies forward or reverse data transfer. Default is 'fwd'.

        deriv : bool, optional
            If True, use du/dp for scatter instead of u/p.  Default is False.

        var_of_interest : str or None
            Specifies the variable of interest to determine relevance.

        """
        x = self._data_xfer.get((target_sys, mode, var_of_interest))
        if x is not None:
            if deriv:
                x.transfer(self.dumat[var_of_interest], self.dpmat[var_of_interest],
                           mode, deriv=True)
            else:
                x.transfer(self.unknowns, self.params, mode)

    def _get_owning_rank(self, name, sizes_table):
        """
        Args
        ----
        name : str
            Name of the variable to find the owning rank for

        sizes_table : list of ordered dicts mapping name to size
            Size info for all vars in all ranks.

        Returns
        -------
        int
            The current rank if it has a local copy of the named variable, else
            the rank of the lowest ranked process that has a local copy.
        """
        if self.comm is None:
            return 0

        if sizes_table[self.comm.rank][name]:
            return self.comm.rank
        else:
            for i in range(self.comm.size):
                if sizes_table[i][name]:
                    return i
            else:
                raise RuntimeError("Can't find a source for '%s' with a non-zero size" %
                                   name)

    def _get_owning_ranks(self):
        """
        Determine the 'owning' rank of each variable and return a dict
        mapping variables to their owning rank. The owning rank is the lowest
        rank where the variable is local.

        """
        ranks = {}

        local_vars = [k for k, m in self.unknowns.items() if not m.get('remote')]
        local_vars.extend([k for k, m in self.params.items() if not m.get('remote')])

        if MPI:
            all_locals = self.comm.allgather(local_vars)
        else:
            all_locals = [local_vars]

        for rank in range(len(all_locals)):
            for v in all_locals[rank]:
                if v not in ranks:
                    ranks[v] = rank

        return ranks

def get_absvarpathnames(var_name, var_dict, dict_name):
    """
    Args
    ----
    var_name : str
        Promoted name of a variable.

    var_dict : dict
        Dictionary of variable metadata, keyed on absolute name.

    dict_name : str
        Name of var_dict (used for error reporting).

    Returns
    -------
    list of str
        The absolute pathnames for the given variables in the
        variable dictionary that map to the given promoted name.
    """

    pnames = [n for n, m in var_dict.items() if m['promoted_name'] == var_name]
    if not pnames:
        raise KeyError("'%s' not found in %s" % (var_name, dict_name))

    return pnames
