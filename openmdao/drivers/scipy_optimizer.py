"""
OpenMDAO Wrapper for the scipy.optimize.minimize family of local optimizers.
"""

from __future__ import print_function

# pylint: disable=E0611,F0401
import numpy as np
from scipy.optimize import minimize

from openmdao.core.driver import Driver
from openmdao.util.recordutil import create_local_meta, update_local_meta

_optimizers = ['Nelder-Mead', 'Powell', 'CG', 'BFGS', 'Newton-CG', 'L-BFGS-B',
               'TNC', 'COBYLA', 'SLSQP']
_gradient_optimizers = ['CG', 'BFGS', 'Newton-CG', 'L-BFGS-B', 'TNC',
                        'SLSQP', 'dogleg', 'trust-ncg']
_bounds_optimizers = ['L-BFGS-B', 'TNC', 'SLSQP']
_constraint_optimizers = ['COBYLA', 'SLSQP']
_constraint_grad_optimizers = ['SLSQP']

# These require Hessian or Hessian-vector product, so they are unsupported
# right now.
_unsupported_optimizers = ['dogleg', 'trust-ncg']


class ScipyOptimizer(Driver):
    """ Driver wrapper for the scipy.optimize.minimize family of local
    optimizers. Inequality constraints are supported by COBYLA and SLSQP,
    but equality constraints are only supported by COBYLA. None of the other
    optimizers support constraints.
    """

    def __init__(self):
        """Initialize the ScipyOptimizer."""

        super(ScipyOptimizer, self).__init__()

        # What we support
        self.supports['Inequality Constraints'] = True
        self.supports['Equality Constraints'] = True
        self.supports['Multiple Objectives'] = False

        # User Options
        self.options.add_option('optimizer', 'SLSQP', values=_optimizers,
                                desc='Name of optimizer to use')
        self.options.add_option('tol', 1.0e-6,
                                desc='Tolerance for termination. For detailed '
                                'control, use solver-specific options.')
        self.options.add_option('maxiter', 200,
                                desc='Maximum number of iterations.')
        self.options.add_option('disp', False,
                                desc='Set to True to print Scipy convergence '
                                'messages')

        # The user places optimizer-specific settings in here.
        self.opt_settings = {}

        self.metadata = None
        self._problem = None
        self.result = None
        self.grad_cache = None
        self.con_idx = {}
        self.cons = None
        self.objs = None

    def run(self, problem):
        """Optimize the problem using our choice of Scipy optimizer.

        Args
        ----
        problem : `Problem`
            Our parent `Problem`.
        """

        # Metadata Setup
        opt = self.options['optimizer']
        self.metadata = create_local_meta(None, opt)
        self.iter_count = 0
        update_local_meta(self.metadata, (self.iter_count,))

        # Initial Run
        problem.root.solve_nonlinear(metadata=self.metadata)

        pmeta = self.get_param_metadata()
        self.objs = list(self.get_objectives().keys())
        con_meta = self.get_constraint_metadata()
        self.cons = list(con_meta.keys())

        self.opt_settings['maxiter'] = self.options['maxiter']
        self.opt_settings['disp'] = self.options['disp']

        # Size Problem
        nparam = 0
        for param in pmeta.values():
            nparam += param['size']
        x_init = np.zeros(nparam)

        # Initial Parameters
        i = 0
        bounds = []
        for name, val in self.get_params().items():
            size = pmeta[name]['size']
            x_init[i:i+size] = val
            i += size

            # Bounds if our optimizer supports them
            if opt in _bounds_optimizers:
                meta_low = pmeta[name]['low']
                meta_high = pmeta[name]['high']
                for j in range(0, size):

                    if isinstance(meta_low, np.ndarray):
                        p_low = meta_low[j]
                    else:
                        p_low = meta_low

                    if isinstance(meta_high, np.ndarray):
                        p_high = meta_high[j]
                    else:
                        p_high = meta_high

                    bounds.append((p_low, p_high))

        # Constraints
        constraints = []
        i = 0
        if opt in _constraint_optimizers:
            for name, meta in con_meta.items():
                size = meta['size']
                for j in range(0, size):
                    con_dict = {}
                    con_dict['type'] = meta['ctype']
                    con_dict['fun'] = self.confunc
                    if opt in _constraint_grad_optimizers:
                        con_dict['jac'] = self.congradfunc
                    con_dict['args'] = [name, j]
                    constraints.append(con_dict)
                self.con_idx[name] = i
                i += size

        # Provide gradients for optimizers that support it
        if opt in _gradient_optimizers:
            jac = self.gradfunc
        else:
            jac = None

        # optimize
        self._problem = problem
        result = minimize(self.objfunc, x_init,
                          #args=(),
                          method=opt,
                          jac=jac,
                          #hess=None,
                          #hessp=None,
                          bounds=bounds,
                          constraints=constraints,
                          tol=self.options['tol'],
                          #callback=None,
                          options=self.opt_settings)

        self._problem = None
        self.result = result

        print('Optimization Complete')
        print('-'*35)
        for key, val in result.items():
            print(key, ':', val)

    def objfunc(self, x_new):
        """ Function that evaluates and returns the objective function. Model
        is executed here.

        Args
        ----
        x_new : ndarray
            Array containing parameter values at new design point.

        Returns
        -------
        float
            Value of the objective function evaluated at the new design point.
        """

        system = self.root
        metadata = self.metadata

        # Pass in new parameters
        i = 0
        for name, meta in self.get_param_metadata().items():
            size = meta['size']
            self.set_param(name, x_new[i:i+size])
            i += size

        self.iter_count += 1
        update_local_meta(metadata, (self.iter_count,))

        system.solve_nonlinear(metadata=metadata)
        for recorder in self.recorders:
            recorder.raw_record(system.params, system.unknowns,
                                system.resids, metadata)

        # Get the objective function evaluations
        for name, obj in self.get_objectives().items():
            f_new = obj
            break

        #print("Functions calculated")
        #print(x_new)
        #print(f_new)

        return f_new

    def confunc(self, x_new, name, idx):
        """ Function that returns the value of the constraint function
        requested in args. Note that this function is called for each
        constraint, so the model is only run when the objective is evaluated.

        Args
        ----
        x_new : ndarray
            Array containing parameter values at new design point.

        name: string
            Name of the constraint to be evaluated.

        idx: float
            Contains index into the constraint array.

        Returns
        -------
        float
            Value of the constraint function.
        """

        cons = self.get_constraints()

        #print("Constraint returned")
        #print(x_new)
        #print(name, idx, cons[name][idx])

        # Note, scipy defines constraints to be satisfied when positive,
        # which is the opposite of OpenMDAO.
        return -cons[name][idx]

    def gradfunc(self, x_new):
        """ Function that evaluates and returns the objective function.
        Gradients for the constraints are also calculated and cached here.

        Args
        ----
        x_new : ndarray
            Array containing parameter values at new design point.

        Returns
        -------
        ndarray
            Gradient of objective with respect to parameter array.
        """

        params = self.get_param_metadata().keys()
        grad = self._problem.calc_gradient(params, self.objs+self.cons,
                                           return_format='array')
        self.grad_cache = grad

        #print("Gradients calculated")
        #print(x_new)
        #print(grad[0, :])

        return grad[0, :]

    def congradfunc(self, x_new, name, idx):
        """ Function that returns the cached gradient of the constraint
        function. Note, scipy calls the constraints one at a time, so the
        gradient is cached when the objective gradient is called.

        Args
        ----
        x_new : ndarray
            Array containing parameter values at new design point.

        name: string
            Name of the constraint to be evaluated.

        idx: float
            Contains index into the constraint array.

        Returns
        -------
        float
            Gradient of the constraint function wrt all params.
        """

        grad = self.grad_cache
        grad_idx = self.con_idx[name] + idx + 1

        #print("Constraint Gradient returned")
        #print(x_new)
        #print(name, idx, grad[grad_idx, :])

        # Note, scipy defines constraints to be satisfied when positive,
        # which is the opposite of OpenMDAO.
        return -grad[grad_idx, :]

