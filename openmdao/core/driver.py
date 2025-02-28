""" Base class for Driver."""

from collections import OrderedDict
from itertools import chain

import numpy as np

from openmdao.core.options import OptionsDictionary
from openmdao.util.recordutil import create_local_meta, update_local_meta


class Driver(object):
    """ Base class for drivers in OpenMDAO. Drivers can only be placed in a
    Problem, and every problem has a Driver. Driver is the simplest driver that
    runs (solves using solve_nonlinear) a problem once.
    """

    def __init__(self):
        super(Driver, self).__init__()
        self.recorders = []

        # What this driver supports
        self.supports = OptionsDictionary(read_only=True)
        self.supports.add_option('Inequality Constraints', True)
        self.supports.add_option('Equality Constraints', True)
        self.supports.add_option('Linear Constraints', False)
        self.supports.add_option('Multiple Objectives', False)
        self.supports.add_option('2-Sided Constraints', False)
        self.supports.add_option('Integer Parameters', False)

        # This driver's options
        self.options = OptionsDictionary()

        self._params = OrderedDict()
        self._objs = OrderedDict()
        self._cons = OrderedDict()

        self._voi_sets = []

        # We take root during setup
        self.root = None

        self.iter_count = 0

    def _setup(self, root):
        """ Prepares some things we need."""
        self.root = root

        item_names = ['Parameter', 'Objective', 'Constraint']
        items = [self._params, self._objs, self._cons]

        for item, item_name in zip(items, item_names):
            for name, meta in item.items():

                # Check validity of variable
                if name not in root.unknowns:
                    msg = "{} '{}' not found in unknowns."
                    msg = msg.format(item_name, name)
                    raise ValueError(msg)

                # Size is useful metadata to save
                if 'indices' in meta:
                    meta['size'] = len(meta['indices'])
                else:
                    meta['size'] = root.unknowns.metadata(name)['size']

    def _map_voi_indices(self):
        poi_indices = {}
        qoi_indices = {}
        for name, meta in chain(self._cons.items(), self._objs.items()):
            # set indices of interest
            if 'indices' in meta:
                qoi_indices[name] = meta['indices']

        for name, meta in self._params.items():
            # set indices of interest
            if 'indices' in meta:
                poi_indices[name] = meta['indices']

        return poi_indices, qoi_indices

    def _of_interest(self, voi_list):
        """Return a list of tuples, with the given voi_list organized
        into tuples based on the previously defined grouping of VOIs.
        """
        vois = []
        done_sets = set()
        for v in voi_list:
            for voi_set in self._voi_sets:
                if voi_set in done_sets:
                    break
                if v in voi_set:
                    vois.append(tuple([x for x in voi_set
                                         if x in voi_list]))
                    done_sets.add(voi_set)
                    break
            else:
                vois.append((v,))
        return vois

    def params_of_interest(self):
        """
        Returns
        -------
        list of tuples of str
            The list of params, organized into tuples according to previously
            defined VOI groups.
        """
        return self._of_interest(self._params)

    def outputs_of_interest(self):
        """
        Returns
        -------
        list of tuples of str
            The list of constraints and objectives, organized into tuples
            according to previously defined VOI groups.
        """
        return self._of_interest(list(chain(self._objs, self._cons)))

    def parallel_derivs(self, vnames):
        """
        Specifies that the named variables of interest are to be grouped
        together so that their derivatives can be solved for concurrently.

        Args
        ----
        vnames : iter of str
            The names of variables of interest that are to be grouped.
        """
        for grp in self._voi_sets:
            for vname in vnames:
                if vname in grp:
                    raise RuntimeError("'%s' cannot be added to VOI set "
                                       "%s because it already "
                                       "exists in VOI set: %s" %
                                         (vname, tuple(vnames), grp))
        param_intsect = set(vnames).intersection(self._params.keys())
        if param_intsect and len(param_intsect) != len(vnames):
            raise RuntimeError("%s cannot be grouped because %s are params and %s are not." %
                                 (vnames, list(param_intsect),
                                 list(set(vnames).difference(param_intsect))))
        self._voi_sets.append(tuple(vnames))

    def add_recorder(self, recorder):
        self.recorders.append(recorder)

    def add_param(self, name, low=None, high=None, indices=None, adder=0.0, scaler=1.0):
        """
        Adds a parameter to this driver.

        Args
        ----
        name : string
           Name of the paramcomp in the root system.

        low : float or ndarray, optional
            Lower boundary for the param

        high : upper or ndarray, optional
            Lower boundary for the param

        indices : iter of int, optional
            If a param is an array, these indicate which entries are of
            interest for derivatives.

        adder: float or ndarray, optional
            Value to add to the model value to get the scaled value. Adder
            is first in precedence.

        scaler: float or ndarray, optional
            value to multiply the model value to get the scaled value. Scaler
            is second in precedence.
        """

        if low is None:
            low = -1e99
        elif isinstance(low, np.ndarray):
            low = low.flatten()

        if high is None:
            high = 1e99
        elif isinstance(high, np.ndarray):
            high = high.flatten()

        if isinstance(adder, np.ndarray):
            adder = adder.flatten()
        if isinstance(scaler, np.ndarray):
            scaler = scaler.flatten()

        # Scale the low and high values
        low = (low + adder)*scaler
        high = (high + adder)*scaler

        param = {}
        param['low'] = low
        param['high'] = high
        param['adder'] = adder
        param['scaler'] = scaler
        if indices:
            param['indices'] = np.array(indices, dtype=int)

        self._params[name] = param

    def get_params(self):
        """ Returns a dict of parameters.

        Returns
        -------
        dict
            Keys are the param object names, and the values are the param
            values.
        """
        uvec = self.root.unknowns
        params = OrderedDict()

        for key, meta in self._params.items():
            scaler = meta['scaler']
            adder = meta['adder']
            flatval = uvec.flat[key]
            if 'indices' in meta:
                flatval = flatval[meta['indices']]
            if isinstance(scaler, np.ndarray) or isinstance(adder, np.ndarray) \
               or scaler != 1.0 or adder != 0.0:
                params[key] = (flatval + adder)*scaler
            else:
                params[key] = flatval

        return params

    def get_param_metadata(self):
        """ Returns a dict of parameter metadata.

        Returns
        -------
        dict
            Keys are the param object names, and the values are the param
            values.
        """
        return self._params

    def set_param(self, name, value):
        """ Sets a parameter.

        Args
        ----
        name : string
           Name of the paramcomp in the root system.

        val : ndarray or float
            value to set the parameter
        """
        scaler = self._params[name]['scaler']
        adder = self._params[name]['adder']
        if isinstance(scaler, np.ndarray) or isinstance(adder, np.ndarray) \
           or scaler != 0.0 or adder != 1.0:
            self.root.unknowns[name] = value/scaler - adder
        else:
            self.root.unknowns[name] = value

    def add_objective(self, name, indices=None, adder=0.0, scaler=1.0):
        """ Adds an objective to this driver.

        Args
        ----
        name : string
            Promoted pathname of the output that will serve as the objective.

        indices : iter of int, optional
            If an objective is an array, these indicate which entries are of
            interest for derivatives.

        adder: float or ndarray, optional
            Value to add to the model value to get the scaled value. Adder
            is first in precedence.

        scaler: float or ndarray, optional
            value to multiply the model value to get the scaled value. Scaler
            is second in precedence.
        """

        if isinstance(adder, np.ndarray):
            adder = adder.flatten()
        if isinstance(scaler, np.ndarray):
            scaler = scaler.flatten()

        obj = {}
        obj['adder'] = adder
        obj['scaler'] = scaler
        if indices:
            obj['indices'] = indices
            if len(indices) > 1 and not self.supports['Multiple Objectives']:
                raise RuntimeError("Multiple objective indices specified for "
                                   "variable '%s', but driver '%s' doesn't "
                                   "support multiple objectives." %
                                   (name, self.pathname))
        self._objs[name] = obj

    def get_objectives(self, return_type='dict'):
        """ Gets all objectives of this driver.

        Args
        ----
        return_type : string
            Set to 'dict' to return a dictionary, or set to 'array' to return a
            flat ndarray.

        Returns
        -------
        dict (for return_type 'dict')
            Key is the objective name string, value is an ndarray with the values.

        ndarray (for return_type 'array')
            Array containing all objective values in the order they were added.
        """
        uvec = self.root.unknowns
        objs = OrderedDict()

        for key, meta in self._objs.items():
            scaler = meta['scaler']
            adder = meta['adder']
            flatval = uvec.flat[key]
            if 'indices' in meta:
                flatval = flatval[meta['indices']]
            if isinstance(scaler, np.ndarray) or isinstance(adder, np.ndarray) \
               or adder != 0.0 or scaler != 1.0:
                objs[key] = (flatval + adder)*scaler
            else:
                objs[key] = flatval

        return objs

    def add_constraint(self, name, ctype='ineq', linear=False, jacs=None,
                       indices=None, adder=0.0, scaler=1.0):
        """ Adds a constraint to this driver.

        Args
        ----
        name : string
            Promoted pathname of the output that will serve as the objective.

        ctype : string
            Set to 'ineq' for inequality constraints, or 'eq' for equality
            constraints. Make sure your driver supports the ctype of constraint
            that you are adding.

        linear : bool, optional
            Set to True if this constraint is linear with respect to all params
            so that it can be calculated once and cached.

        jacs : dict of functions, optional
            Dictionary of user-defined functions that return the flattened
            Jacobian of this constraint with repsect to the params of
            this driver, as indicated by the dictionary keys. Default is None
            to let OpenMDAO calculate all derivatives.

        indices : iter of int, optional
            If a constraint is an array, these indicate which entries are of
            interest for derivatives.

        adder: float or ndarray, optional
            Value to add to the model value to get the scaled value. Adder
            is first in precedence.

        scaler: float or ndarray, optional
            value to multiply the model value to get the scaled value. Scaler
            is second in precedence.
        """

        if ctype=='eq' and self.supports['Equality Constraints'] is False:
            msg = "Driver does not support equality constraint '{}'."
            raise RuntimeError(msg.format(name))
        if ctype=='ineq' and self.supports['Inequality Constraints'] is False:
            msg = "Driver does not support inequality constraint '{}'."
            raise RuntimeError(msg.format(name))

        if isinstance(adder, np.ndarray):
            adder = adder.flatten()
        if isinstance(scaler, np.ndarray):
            scaler = scaler.flatten()

        con = {}
        con['linear'] = linear
        con['ctype'] = ctype
        con['adder'] = adder
        con['scaler'] = scaler
        if indices:
            con['indices'] = indices
        self._cons[name] = con

    def get_constraints(self, ctype='all', lintype='all', return_type='dict'):
        """ Gets all constraints for this driver.

        Args
        ----
        ctype : string
            Default is 'all'. Optionally return just the inequality constraints
            with 'ineq' or the equality constraints with 'eq'.

        lintype : string
            Default is 'all'. Optionally return just the linear constraints
            with 'linear' or the nonlinear constraints with 'nonlinear'.

        return_type : string
            Set to 'dict' to return a dictionary, or set to 'array' to return a
            flat ndarray.

        Returns
        -------
        dict (for return_type 'dict')
            Key is the constraint name string, value is an ndarray with the values.

        ndarray (for return_type 'array')
            Array containing all constraint values in the order they were added.
        """
        uvec = self.root.unknowns
        cons = OrderedDict()

        for key, meta in self._cons.items():

            if lintype=='linear' and meta['linear']==False:
                continue

            if lintype=='nonlinear' and meta['linear']==True:
                continue

            if ctype=='eq' and meta['ctype']=='ineq':
                continue

            if ctype=='ineq' and meta['ctype']=='eq':
                continue

            scaler = meta['scaler']
            adder = meta['adder']
            flatval = uvec.flat[key]
            if 'indices' in meta:
                flatval = flatval[meta['indices']]
            if isinstance(scaler, np.ndarray) or isinstance(adder, np.ndarray) \
               or adder != 0.0 or scaler != 1.0:
                cons[key] = (flatval + adder)*scaler
            else:
                cons[key] = flatval

        return cons

    def get_constraint_metadata(self):
        """ Returns a dict of constraint metadata.

        Returns
        -------
        dict
            Keys are the constraint object names, and the values are the param
            values.
        """
        return self._cons

    def run(self, problem):
        """ Runs the driver. This function should be overriden when inheriting.

        Args
        ----
        problem : `Problem`
            Our parent `Problem`.
        """
        system = problem.root

        # Metadata Setup
        self.iter_count += 1
        metadata = create_local_meta(None, 'Driver')
        system.ln_solver.local_meta = metadata
        update_local_meta(metadata, (self.iter_count,))

        # Solve the system once and record results.
        system.solve_nonlinear(metadata=metadata)
        for recorder in self.recorders:
            recorder.raw_record(system.params, system.unknowns, system.resids, metadata)
