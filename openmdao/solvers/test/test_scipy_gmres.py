""" Unit test for the Scipy GMRES linear solver. """

import unittest
import numpy as np

from openmdao.core.group import Group
from openmdao.core.problem import Problem
from openmdao.components.paramcomp import ParamComp
from openmdao.components.execcomp import ExecComp
from openmdao.solvers.scipy_gmres import ScipyGMRES
from openmdao.test.converge_diverge import ConvergeDiverge, SingleDiamond, \
                                           ConvergeDivergeGroups, SingleDiamondGrouped
from openmdao.test.sellar import SellarDerivativesGrouped
from openmdao.test.simplecomps import SimpleCompDerivMatVec, FanOut, FanIn, \
                                      FanOutGrouped, \
                                      FanInGrouped, ArrayComp2D
from openmdao.test.testutil import assert_rel_error


class TestScipyGMRES(unittest.TestCase):

    def test_simple_matvec(self):
        group = Group()
        group.add('x_param', ParamComp('x', 1.0), promotes=['*'])
        group.add('mycomp', SimpleCompDerivMatVec(), promotes=['x', 'y'])

        prob = Problem()
        prob.root = group
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        J = prob.calc_gradient(['x'], ['y'], mode='fwd', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

        J = prob.calc_gradient(['x'], ['y'], mode='rev', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

    def test_simple_matvec_subbed(self):
        group = Group()
        group.add('mycomp', SimpleCompDerivMatVec(), promotes=['x', 'y'])

        prob = Problem()
        prob.root = Group()
        prob.root.add('x_param', ParamComp('x', 1.0), promotes=['*'])
        prob.root.add('sub', group, promotes=['*'])

        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        J = prob.calc_gradient(['x'], ['y'], mode='fwd', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

        J = prob.calc_gradient(['x'], ['y'], mode='rev', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

    def test_array2D(self):
        group = Group()
        group.add('x_param', ParamComp('x', np.ones((2, 2))), promotes=['*'])
        group.add('mycomp', ArrayComp2D(), promotes=['x', 'y'])

        prob = Problem()
        prob.root = group
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        J = prob.calc_gradient(['x'], ['y'], mode='fwd', return_format='dict')
        Jbase = prob.root.mycomp._jacobian_cache
        diff = np.linalg.norm(J['y']['x'] - Jbase['y', 'x'])
        assert_rel_error(self, diff, 0.0, 1e-8)

        J = prob.calc_gradient(['x'], ['y'], mode='rev', return_format='dict')
        diff = np.linalg.norm(J['y']['x'] - Jbase['y', 'x'])
        assert_rel_error(self, diff, 0.0, 1e-8)

    def test_simple_in_group_matvec(self):
        group = Group()
        sub = group.add('sub', Group(), promotes=['x', 'y'])
        group.add('x_param', ParamComp('x', 1.0), promotes=['*'])
        sub.add('mycomp', SimpleCompDerivMatVec(), promotes=['x', 'y'])

        prob = Problem()
        prob.root = group
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        J = prob.calc_gradient(['x'], ['y'], mode='fwd', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

        J = prob.calc_gradient(['x'], ['y'], mode='rev', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

    def test_simple_jac(self):
        group = Group()
        group.add('x_param', ParamComp('x', 1.0), promotes=['*'])
        group.add('mycomp', ExecComp(['y=2.0*x']), promotes=['x', 'y'])

        prob = Problem()
        prob.root = group
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        J = prob.calc_gradient(['x'], ['y'], mode='fwd', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

        J = prob.calc_gradient(['x'], ['y'], mode='rev', return_format='dict')
        assert_rel_error(self, J['y']['x'][0][0], 2.0, 1e-6)

    def test_fan_out(self):

        prob = Problem()
        prob.root = FanOut()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        param_list = ['p.x']
        unknown_list = ['comp2.y', "comp3.y"]

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp2.y']['p.x'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['comp3.y']['p.x'][0][0], 15.0, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp2.y']['p.x'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['comp3.y']['p.x'][0][0], 15.0, 1e-6)

    def test_fan_out_grouped(self):

        prob = Problem()
        prob.root = FanOutGrouped()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        param_list = ['p.x']
        unknown_list = ['sub.comp2.y', "sub.comp3.y"]

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['sub.comp2.y']['p.x'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['sub.comp3.y']['p.x'][0][0], 15.0, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['sub.comp2.y']['p.x'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['sub.comp3.y']['p.x'][0][0], 15.0, 1e-6)

    def test_fan_in(self):

        prob = Problem()
        prob.root = FanIn()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        param_list = ['p1.x1', 'p2.x2']
        unknown_list = ['comp3.y']

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp3.y']['p1.x1'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['comp3.y']['p2.x2'][0][0], 35.0, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp3.y']['p1.x1'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['comp3.y']['p2.x2'][0][0], 35.0, 1e-6)

    def test_fan_in_grouped(self):

        prob = Problem()
        prob.root = FanInGrouped()
        prob.root.ln_solver = ScipyGMRES()

        param_list = ['p1.x1', 'p2.x2']
        unknown_list = ['comp3.y']

        prob.setup(check=False)
        prob.run()

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp3.y']['p1.x1'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['comp3.y']['p2.x2'][0][0], 35.0, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp3.y']['p1.x1'][0][0], -6.0, 1e-6)
        assert_rel_error(self, J['comp3.y']['p2.x2'][0][0], 35.0, 1e-6)

    def test_converge_diverge(self):

        prob = Problem()
        prob.root = ConvergeDiverge()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        param_list = ['p.x']
        unknown_list = ['comp7.y1']

        prob.run()

        # Make sure value is fine.
        assert_rel_error(self, prob['comp7.y1'], -102.7, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp7.y1']['p.x'][0][0], -40.75, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp7.y1']['p.x'][0][0], -40.75, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='fd', return_format='dict')
        assert_rel_error(self, J['comp7.y1']['p.x'][0][0], -40.75, 1e-6)

    def test_converge_diverge_groups(self):

        prob = Problem()
        prob.root = ConvergeDivergeGroups()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        # Make sure value is fine.
        assert_rel_error(self, prob['comp7.y1'], -102.7, 1e-6)

        param_list = ['p.x']
        unknown_list = ['comp7.y1']

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp7.y1']['p.x'][0][0], -40.75, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp7.y1']['p.x'][0][0], -40.75, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='fd', return_format='dict')
        assert_rel_error(self, J['comp7.y1']['p.x'][0][0], -40.75, 1e-6)

    def test_single_diamond(self):

        prob = Problem()
        prob.root = SingleDiamond()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        param_list = ['p.x']
        unknown_list = ['comp4.y1', 'comp4.y2']

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp4.y1']['p.x'][0][0], 25, 1e-6)
        assert_rel_error(self, J['comp4.y2']['p.x'][0][0], -40.5, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp4.y1']['p.x'][0][0], 25, 1e-6)
        assert_rel_error(self, J['comp4.y2']['p.x'][0][0], -40.5, 1e-6)

    def test_single_diamond_grouped(self):

        prob = Problem()
        prob.root = SingleDiamondGrouped()
        prob.root.ln_solver = ScipyGMRES()
        prob.setup(check=False)
        prob.run()

        param_list = ['p.x']
        unknown_list = ['comp4.y1', 'comp4.y2']

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        assert_rel_error(self, J['comp4.y1']['p.x'][0][0], 25, 1e-6)
        assert_rel_error(self, J['comp4.y2']['p.x'][0][0], -40.5, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        assert_rel_error(self, J['comp4.y1']['p.x'][0][0], 25, 1e-6)
        assert_rel_error(self, J['comp4.y2']['p.x'][0][0], -40.5, 1e-6)

        J = prob.calc_gradient(param_list, unknown_list, mode='fd', return_format='dict')
        assert_rel_error(self, J['comp4.y1']['p.x'][0][0], 25, 1e-6)
        assert_rel_error(self, J['comp4.y2']['p.x'][0][0], -40.5, 1e-6)

    def test_sellar_derivs_grouped(self):

        prob = Problem()
        prob.root = SellarDerivativesGrouped()

        prob.root.mda.nl_solver.options['atol'] = 1e-12
        prob.setup(check=False)
        prob.run()

        # Just make sure we are at the right answer
        assert_rel_error(self, prob['y1'], 25.58830273, .00001)
        assert_rel_error(self, prob['y2'], 12.05848819, .00001)

        param_list = ['x', 'z']
        unknown_list = ['obj', 'con1', 'con2']

        Jbase = {}
        Jbase['con1'] = {}
        Jbase['con1']['x'] = -0.98061433
        Jbase['con1']['z'] = np.array([-9.61002285, -0.78449158])
        Jbase['con2'] = {}
        Jbase['con2']['x'] = 0.09692762
        Jbase['con2']['z'] = np.array([1.94989079, 1.0775421 ])
        Jbase['obj'] = {}
        Jbase['obj']['x'] = 2.98061392
        Jbase['obj']['z'] = np.array([9.61001155, 1.78448534])

        J = prob.calc_gradient(param_list, unknown_list, mode='fwd', return_format='dict')
        for key1, val1 in Jbase.items():
            for key2, val2 in val1.items():
                assert_rel_error(self, J[key1][key2], val2, .00001)

        J = prob.calc_gradient(param_list, unknown_list, mode='rev', return_format='dict')
        for key1, val1 in Jbase.items():
            for key2, val2 in val1.items():
                assert_rel_error(self, J[key1][key2], val2, .00001)

        prob.root.fd_options['form'] = 'central'
        J = prob.calc_gradient(param_list, unknown_list, mode='fd', return_format='dict')
        for key1, val1 in Jbase.items():
            for key2, val2 in val1.items():
                assert_rel_error(self, J[key1][key2], val2, .00001)


if __name__ == "__main__":
    unittest.main()

