""" Some simple test components. """

import numpy as np
import scipy.sparse

from openmdao.core.component import Component
from openmdao.core.group import Group
from openmdao.core.parallelgroup import ParallelGroup

from openmdao.components.paramcomp import ParamComp
from openmdao.components.execcomp import ExecComp


class SimpleComp(Component):
    """ The simplest component you can imagine. """

    def __init__(self, multiplier=2.0):
        super(SimpleComp, self).__init__()

        self.multiplier = multiplier

        # Params
        self.add_param('x', 3.0)

        # Unknowns
        self.add_output('y', 5.5)

    def solve_nonlinear(self, params, unknowns, resids):
        """ Doesn't do much. """
        unknowns['y'] = self.multiplier*params['x']


class SimpleCompDerivMatVec(SimpleComp):
    """ The simplest component you can imagine, this time with derivatives
    defined using apply_linear. """

    def apply_linear(self, params, unknowns, dparams, dunknowns, dresids,
                     mode):
        """Returns the product of the incoming vector with the Jacobian."""

        if mode == 'fwd':
            dresids['y'] += self.multiplier*dparams['x']

        elif mode == 'rev':
            dparams['x'] = self.multiplier*dresids['y']


class SimpleArrayComp(Component):
    """A fairly simple array component."""

    def __init__(self):
        super(SimpleArrayComp, self).__init__()

        # Params
        self.add_param('x', np.zeros([2]))

        # Unknowns
        self.add_output('y', np.zeros([2]))

    def solve_nonlinear(self, params, unknowns, resids):
        """ Doesn't do much. """

        unknowns['y'][0] = 2.0*params['x'][0] + 7.0*params['x'][1]
        unknowns['y'][1] = 5.0*params['x'][0] - 3.0*params['x'][1]
        # print(self.name, "ran", params['x'], unknowns['y'])

    def jacobian(self, params, unknowns, resids):
        """Analytical derivatives."""

        dy1_dx1 = 2.0
        dy1_dx2 = 7.0
        dy2_dx1 = 5.0
        dy2_dx2 = -3.0
        J = {}
        J[('y', 'x')] = np.array([[dy1_dx1, dy1_dx2], [dy2_dx1, dy2_dx2]])

        return J


class ArrayComp2D(Component):
    """2D Array component."""

    def __init__(self):
        super(ArrayComp2D, self).__init__()

        # Params
        self.add_param('x', np.zeros((2, 2)))

        # Unknowns
        self.add_output('y', np.zeros((2, 2)))

    def solve_nonlinear(self, params, unknowns, resids):
        """ Doesn't do much."""

        x = params['x']
        y = np.zeros((2, 2))

        y[0][0] = 2.0*x[0][0] + 1.0*x[0][1] + \
                  3.0*x[1][0] + 7.0*x[1][1]

        y[0][1] = 4.0*x[0][0] + 2.0*x[0][1] + \
                  6.0*x[1][0] + 5.0*x[1][1]

        y[1][0] = 3.0*x[0][0] + 6.0*x[0][1] + \
                  9.0*x[1][0] + 8.0*x[1][1]

        y[1][1] = 1.0*x[0][0] + 3.0*x[0][1] + \
                  2.0*x[1][0] + 4.0*x[1][1]

        unknowns['y'] = y

    def jacobian(self, params, unknowns, resids):
        """Analytical derivatives."""

        J = {}
        J['y', 'x'] = np.array([[2.0, 1.0, 3.0, 7.0],
                                [4.0, 2.0, 6.0, 5.0],
                                [3.0, 6.0, 9.0, 8.0],
                                [1.0, 3.0, 2.0, 4.0]])
        return J


class SimpleSparseArrayComp(Component):
    """A fairly simple sparse array component."""

    def __init__(self):
        super(SimpleSparseArrayComp, self).__init__()

        # Params
        self.add_param('x', np.zeros([4]))

        # Unknowns
        self.add_output('y', np.zeros([4]))

    def solve_nonlinear(self, params, unknowns, resids):
        """ Doesn't do much."""

        unknowns['y'][0] = 2.0*params['x'][0] + 7.0*params['x'][3]
        unknowns['y'][2] = 5.0*params['x'][1] - 3.0*params['x'][2]
        # print(self.name, "ran", params['x'], unknowns['y'])

    def jacobian(self, params, unknowns, resids):
        """Analytical derivatives."""

        dy1_dx1 = 2.0
        dy1_dx2 = 7.0
        dy2_dx1 = 5.0
        dy2_dx2 = -3.0
        data = [dy1_dx1, dy1_dx2, dy2_dx1, dy2_dx2]
        row = [0, 0, 2, 2]
        col = [0, 3, 1, 2]
        J = {}
        J[('y', 'x')] = scipy.sparse.csc_matrix((data, (row, col)),
                                                shape=(4, 4))

        return J


class SimpleImplicitComp(Component):
    """ A Simple Implicit Component with an additional output equation.

    f(x,z) = xz + z - 4
    y = x + 2z

    Sol: when x = 0.5, z = 2.666

    Coupled derivs:

    y = x + 8/(x+1)
    dy_dx = 1 - 8/(x+1)**2 = -2.5555555555555554

    z = 4/(x+1)
    dz_dx = -4/(x+1)**2 = -1.7777777777777777
    """

    def __init__(self):
        super(SimpleImplicitComp, self).__init__()

        # Params
        self.add_param('x', 0.5, low=0.01, high=1.0)

        # Unknowns
        self.add_output('y', 0.0)

        # States
        self.add_state('z', 0.0)

        self.maxiter = 10
        self.atol = 1.0e-12

    def solve_nonlinear(self, params, unknowns, resids):
        """ Simple iterative solve. (Babylonian method)."""

        x = params['x']
        z = unknowns['z']
        znew = z

        iter = 0
        eps = 1.0e99
        while iter < self.maxiter and abs(eps) > self.atol:
            z = znew
            znew = 4.0 - x*z

            eps = x*znew + znew - 4.0

        unknowns['z'] = znew
        unknowns['y'] = x + 2.0*znew

        resids['z'] = eps

    def apply_nonlinear(self, params, unknowns, resids):
        """ Don't solve; just calculate the residual."""

        x = params['x']
        z = unknowns['z']
        resids['z'] = x*z + z - 4.0

        # Output equations need to evaluate a residual just like an explicit comp.
        resids['y'] = x + 2.0*z - unknowns['y']

    def jacobian(self, params, unknowns, resids):
        """Analytical derivatives."""

        J = {}

        # Output equation
        J[('y', 'x')] = np.array([1.0])
        J[('y', 'z')] = np.array([2.0])

        # State equation
        J[('z', 'z')] = np.array([params['x'] + 1.0])
        J[('z', 'x')] = np.array([unknowns['z']])

        return J


class SimplePassByObjComp(Component):
    """ The simplest component you can imagine. """

    def __init__(self):
        super(SimplePassByObjComp, self).__init__()

        # Params
        self.add_param('x', '')

        # Unknowns
        self.add_output('y', '')

    def solve_nonlinear(self, params, unknowns, resids):
        """ Doesn't do much."""

        unknowns['y'] = params['x']+self.name


class Paraboloid(Component):
    """ Evaluates the equation f(x,y) = (x-3)^2 + xy + (y+4)^2 - 3 """

    def __init__(self):
        super(Paraboloid, self).__init__()

        # Params
        self.add_param('x', 1.0)
        self.add_param('y', 1.0)

        # Unknowns
        self.add_output('f_xy', 0.0)

    def solve_nonlinear(self, params, unknowns, resids):
        """f(x,y) = (x-3)^2 + xy + (y+4)^2 - 3
        Optimal solution (minimum): x = 6.6667; y = -7.3333
        """

        x = params['x']
        y = params['y']

        unknowns['f_xy'] = (x-3.0)**2 + x*y + (y+4.0)**2 - 3.0

    def jacobian(self, params, unknowns, resids):
        """Analytical derivatives."""

        x = params['x']
        y = params['y']
        J = {}

        J['f_xy', 'x'] = 2.0*x - 6.0 + y
        J['f_xy', 'y']  = 2.0*y + 8.0 + x

        return J


class FanOut(Group):
    """ Topology where one comp broadcasts an output to two target
    components."""

    def __init__(self):
        super(FanOut, self).__init__()

        self.add('p', ParamComp('x', 1.0))
        self.add('comp1', ExecComp(['y=3.0*x']))
        self.add('comp2', ExecComp(['y=-2.0*x']))
        self.add('comp3', ExecComp(['y=5.0*x']))

        self.connect("comp1.y", "comp2.x")
        self.connect("comp1.y", "comp3.x")
        self.connect("p.x", "comp1.x")


class FanOutGrouped(Group):
    """ Topology where one comp broadcasts an output to two target
    components."""

    def __init__(self):
        super(FanOutGrouped, self).__init__()

        self.add('p', ParamComp('x', 1.0))
        self.add('comp1', ExecComp(['y=3.0*x']))
        sub = self.add('sub', ParallelGroup())
        sub.add('comp2', ExecComp(['y=-2.0*x']))
        sub.add('comp3', ExecComp(['y=5.0*x']))

        self.add('c2', ExecComp(['y=x']))
        self.add('c3', ExecComp(['y=x']))
        self.connect('sub.comp2.y', 'c2.x')
        self.connect('sub.comp3.y', 'c3.x')

        self.connect("comp1.y", "sub.comp2.x")
        self.connect("comp1.y", "sub.comp3.x")
        self.connect("p.x", "comp1.x")


class FanIn(Group):
    """ Topology where two comps feed a single comp."""

    def __init__(self):
        super(FanIn, self).__init__()

        self.add('p1', ParamComp('x1', 1.0))
        self.add('p2', ParamComp('x2', 1.0))
        self.add('comp1', ExecComp(['y=-2.0*x']))
        self.add('comp2', ExecComp(['y=5.0*x']))
        self.add('comp3', ExecComp(['y=3.0*x1+7.0*x2']))

        self.connect("comp1.y", "comp3.x1")
        self.connect("comp2.y", "comp3.x2")
        self.connect("p1.x1", "comp1.x")
        self.connect("p2.x2", "comp2.x")


class FanInGrouped(Group):
    """
    Topology where two comps in a Group feed a single comp
    outside of that Group.
    """

    def __init__(self):
        super(FanInGrouped, self).__init__()

        self.add('p1', ParamComp('x1', 1.0))
        self.add('p2', ParamComp('x2', 1.0))
        sub = self.add('sub', ParallelGroup())

        sub.add('comp1', ExecComp(['y=-2.0*x']))
        sub.add('comp2', ExecComp(['y=5.0*x']))
        self.add('comp3', ExecComp(['y=3.0*x1+7.0*x2']))

        self.connect("sub.comp1.y", "comp3.x1")
        self.connect("sub.comp2.y", "comp3.x2")
        self.connect("p1.x1", "sub.comp1.x")
        self.connect("p2.x2", "sub.comp2.x")

class RosenSuzuki(Component):
    """ From the CONMIN User's Manual:
    EXAMPLE 1 - CONSTRAINED ROSEN-SUZUKI FUNCTION.

         MINIMIZE OBJ = X(1)**2 - 5*X(1) + X(2)**2 - 5*X(2) +
                        2*X(3)**2 - 21*X(3) + X(4)**2 + 7*X(4) + 50

         Subject to:

              G(1) = X(1)**2 + X(1) + X(2)**2 - X(2) +
                     X(3)**2 + X(3) + X(4)**2 - X(4) - 8   .LE.0

              G(2) = X(1)**2 - X(1) + 2*X(2)**2 + X(3)**2 +
                     2*X(4)**2 - X(4) - 10                  .LE.0

              G(3) = 2*X(1)**2 + 2*X(1) + X(2)**2 - X(2) +
                     X(3)**2 - X(4) - 5                     .LE.0

    This problem is solved beginning with an initial X-vector of
         X = (1.0, 1.0, 1.0, 1.0)
    The optimum design is known to be
         OBJ = 6.000
    and the corresponding X-vector is
         X = (0.0, 1.0, 2.0, -1.0)
    """

    def __init__(self):
        super(RosenSuzuki, self).__init__()

        # parameters
        self.add_param('x', np.array([1., 1., 1., 1.])) # low=-10, high=99

        # unknowns
        self.add_output('g', np.array([1., 1., 1.]))    # constraints
        self.add_output('f', 0.)                        # objective

        # optimal solution
        self.opt_objective = 6.
        self.opt_design_vars = [0., 1., 2., -1.]

    def solve_nonlinear(self, params, unknowns, resids):
        """calculate the new objective and constraint values"""
        x = params['x']

        f = (x[0]**2 - 5.*x[0] + x[1]**2 - 5.*x[1] +
             2.*x[2]**2 - 21.*x[2] + x[3]**2 + 7.*x[3] + 50)

        unknowns['f'] = f

        g = [1., 1., 1.]
        g[0] = (x[0]**2 + x[0] + x[1]**2 - x[1] +
                x[2]**2 + x[2] + x[3]**2 - x[3] - 8)
        g[1] = (x[0]**2 - x[0] + 2*x[1]**2 + x[2]**2 +
                2*x[3]**2 - x[3] - 10)
        g[2] = (2*x[0]**2 + 2*x[0] + x[1]**2 - x[1] +
                x[2]**2 - x[3] - 5)

        unknowns['g'] = np.array(g)

    def jacobian(self, params, unknowns, resids):
        """Analytical derivatives"""
        J = {}

        x = params['x']

        J[('f', 'x')] = np.array([
            [2*x[0]-5, 2*x[1]-5, 4*x[2]-21, 2*x[3]+7]
        ])

        J[('g', 'x')] = np.array([
            [2*x[0]+1, 2*x[1]-1, 2*x[2]+1, 2*x[3]-1],
            [2*x[0]-1, 4*x[1],   2*x[2],   4*x[3]-1],
            [4*x[0]+2, 2*x[1]-1, 2*x[2],   -1],
        ])

        return J
