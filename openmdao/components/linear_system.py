""" A component that solves a linear system. """

import numpy as np

from openmdao.core.component import Component


class LinearSystem(Component):
    """ A component that solves a linear system Ax=b where A and x are params
    and x is a state."""

    def __init__(self, size):
        super(LinearSystem, self).__init__()
        self.size = size

        self.add_param("A", val=np.eye(size))
        self.add_param("b", val=np.ones(size))

        self.add_state("x", val=np.zeros(size))

    def solve_nonlinear(self, params, unknowns, resids):
        """ Use numpy to solve Ax=b for x."""

        unknowns['x'] = np.linalg.solve(params['A'], params['b'])
        resids['x'] = params['A'].dot(unknowns['x']) - params['b']

    def apply_nonlinear(self, params, unknowns, resids):
        """Evaluating residual for given state."""

        resids['x'] = params['A'].dot(unknowns['x']) - params['b']

    def apply_linear(self, params, unknowns, dparams, dunknowns, dresids, mode):
        """ Apply the derivative of state variable with respect to
        everything."""

        if mode == 'fwd':

            if 'x' in dunknowns:
                dresids['x'] += params['A'].dot(dunknowns['x'])
            if 'A' in dparams:
                dresids['x'] += dparams['A'].dot(unknowns['x'])
            if 'b' in dparams:
                dresids['x'] -= dparams['b']

        elif mode == 'rev':

            if 'x' in dunknowns:
                dunknowns['x'] += params['A'].T.dot(dresids['x'])
            if 'A' in dparams:
                dparams['A'] += np.outer(unknowns['x'], dresids['x']).T
            if 'b' in dparams:
                dparams['b'] -= dresids['x']
