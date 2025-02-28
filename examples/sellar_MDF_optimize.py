""" Optimize the Sellar problem using SLSQP."""

import numpy as np

from openmdao.components.execcomp import ExecComp
from openmdao.components.paramcomp import ParamComp
from openmdao.core.component import Component
from openmdao.core.group import Group
from openmdao.solvers.nl_gauss_seidel import NLGaussSeidel


class SellarDis1(Component):
    """Component containing Discipline 1."""

    def __init__(self):
        super(SellarDis1, self).__init__()

        # Global Design Variable
        self.add_param('z', val=np.zeros(2))

        # Local Design Variable
        self.add_param('x', val=0.)

        # Coupling parameter
        self.add_param('y2', val=0.)

        # Coupling output
        self.add_output('y1', val=1.0)

    def solve_nonlinear(self, params, unknowns, resids):
        """Evaluates the equation
        y1 = z1**2 + z2 + x1 - 0.2*y2"""

        z1 = params['z'][0]
        z2 = params['z'][1]
        x1 = params['x']
        y2 = params['y2']

        unknowns['y1'] = z1**2 + z2 + x1 - 0.2*y2

    def jacobian(self, params, unknowns, resids):
        """ Jacobian for Sellar discipline 1."""
        J = {}

        J['y1','y2'] = -0.2
        J['y1','z'] = np.array([[2*params['z'][0], 1.0]])
        J['y1','x'] = 1.0

        return J


class SellarDis2(Component):
    """Component containing Discipline 2."""

    def __init__(self):
        super(SellarDis2, self).__init__()

        # Global Design Variable
        self.add_param('z', val=np.zeros(2))

        # Coupling parameter
        self.add_param('y1', val=0.)

        # Coupling output
        self.add_output('y2', val=1.0)

    def solve_nonlinear(self, params, unknowns, resids):
        """Evaluates the equation
        y2 = y1**(.5) + z1 + z2"""

        z1 = params['z'][0]
        z2 = params['z'][1]
        y1 = params['y1']

        # Note: this may cause some issues. However, y1 is constrained to be
        # above 3.16, so lets just let it converge, and the optimizer will
        # throw it out
        y1 = abs(y1)

        unknowns['y2'] = y1**.5 + z1 + z2

    def jacobian(self, params, unknowns, resids):
        """ Jacobian for Sellar discipline 2."""
        J = {}

        J['y2', 'y1'] = .5*params['y1']**-.5
        J['y2', 'z'] = np.array([[1.0, 1.0]])

        return J


class SellarDerivatives(Group):
    """ Group containing the Sellar MDA. This version uses the disciplines
    with derivatives."""

    def __init__(self):
        super(SellarDerivatives, self).__init__()

        self.add('px', ParamComp('x', 1.0), promotes=['*'])
        self.add('pz', ParamComp('z', np.array([5.0, 2.0])), promotes=['*'])

        self.add('d1', SellarDis1(), promotes=['*'])
        self.add('d2', SellarDis2(), promotes=['*'])

        self.add('obj_cmp', ExecComp('obj = x**2 + z[1] + y1 + exp(-y2)',
                                     z=np.array([0.0, 0.0]), x=0.0, d1=0.0, d2=0.0),
                 promotes=['*'])

        self.add('con_cmp1', ExecComp('con1 = 3.16 - y1'), promotes=['*'])
        self.add('con_cmp2', ExecComp('con2 = y2 - 24.0'), promotes=['*'])

        self.nl_solver = NLGaussSeidel()
        self.nl_solver.options['atol'] = 1.0e-12


if __name__ == '__main__':
    # Setup and run the model.

    from openmdao.core.problem import Problem
    from openmdao.drivers.scipy_optimizer import ScipyOptimizer

    top = Problem()
    top.root = SellarDerivatives()

    top.driver = ScipyOptimizer()
    top.driver.options['optimizer'] = 'SLSQP'
    top.driver.options['tol'] = 1.0e-8

    top.driver.add_param('z', low=np.array([-10.0, 0.0]),
                         high=np.array([10.0, 10.0]))
    top.driver.add_param('x', low=0.0, high=10.0)

    top.driver.add_objective('obj')
    top.driver.add_constraint('con1')
    top.driver.add_constraint('con2')

    top.setup()
    top.run()

    print("\n")
    print( "Minimum found at (%f, %f, %f)" % (top['z'][0], \
                                             top['z'][1], \
                                             top['x']))
    print("Coupling vars: %f, %f" % (top['y1'], top['y2']))
    print("Minimum objective: ", top['obj'])
