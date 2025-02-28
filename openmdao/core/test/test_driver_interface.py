""" Test for the Driver class -- basic driver interface."""

from pprint import pformat
import unittest

import numpy as np

from openmdao.components.execcomp import ExecComp
from openmdao.components.paramcomp import ParamComp
from openmdao.core.driver import Driver
from openmdao.core.group import Group
from openmdao.core.options import OptionsDictionary
from openmdao.core.problem import Problem
from openmdao.test.paraboloid import Paraboloid
from openmdao.test.simplecomps import ArrayComp2D
from openmdao.test.sellar import SellarDerivatives


class MySimpleDriver(Driver):

    def __init__(self):
        super(MySimpleDriver, self).__init__()

        # What we support
        self.supports['Inequality Constraints'] = True
        self.supports['Equality Constraints'] = False
        self.supports['Linear Constraints'] = False
        self.supports['Multiple Objectives'] = False

        # My driver options
        self.options = OptionsDictionary()
        self.options.add_option('tol', 1e-4)
        self.options.add_option('maxiter', 10)

        self.alpha = .01
        self.violated = []

    def run(self, problem):
        """ Mimic a very simplistic unconstrained optimization."""

        # Get dicts with pointers to our vectors
        params = self.get_params()
        objective = self.get_objectives()
        constraints = self.get_constraints()

        param_list = params.keys()
        objective_names = list(objective.keys())
        constraint_names = list(constraints.keys())
        unknown_list = objective_names + constraint_names

        itercount = 0
        while itercount < self.options['maxiter']:

            # Run the model
            problem.root.solve_nonlinear()
            #print('z1: %f, z2: %f, x1: %f, y1: %f, y2: %f' % (problem['z'][0],
                                                              #problem['z'][1],
                                                              #problem['x'],
                                                              #problem['y1'],
                                                              #problem['y2']))
            #print('obj: %f, con1: %f, con2: %f' % (problem['obj'], problem['con1'],
                                                   #problem['con2']))

            # Calculate gradient
            J = problem.calc_gradient(param_list, unknown_list, return_format='dict')

            objective = self.get_objectives()
            constraints = self.get_constraints()

            for key1 in objective_names:
                for key2 in param_list:

                    grad = J[key1][key2] * objective[key1]
                    new_val = params[key2] - self.alpha*grad

                    # Set parameter
                    self.set_param(key2, new_val)

            self.violated = []
            for name, val in constraints.items():
                if np.linalg.norm(val) > 0.0:
                    self.violated.append(name)

            itercount += 1


class TestDriver(unittest.TestCase):

    def test_mydriver(self):

        prob = Problem()
        root = prob.root = SellarDerivatives()

        prob.driver = MySimpleDriver()
        prob.driver.add_param('z', low=-100.0, high=100.0)

        prob.driver.add_objective('obj')
        prob.driver.add_constraint('con1')
        prob.driver.add_constraint('con2')

        prob.setup(check=False)
        prob.run()

        obj = prob['obj']
        self.assertLess(obj, 28.0)

    def test_scaler_adder(self):

        class ScaleAddDriver(Driver):

            def run(self, problem):
                """ Save away scaled info."""

                params = self.get_params()
                param_meta = self.get_param_metadata()

                self.set_param('x', 0.5)
                problem.root.solve_nonlinear()

                objective = self.get_objectives()
                constraint = self.get_constraints()

                # Stuff we saved should be in the scaled coordinates.
                self.param = params['x']
                self.obj_scaled = objective['f_xy']
                self.con_scaled = constraint['con']
                self.param_high = param_meta['x']['high']
                self.param_low = param_meta['x']['low']

        prob = Problem()
        root = prob.root = Group()
        driver = prob.driver = ScaleAddDriver()

        root.add('p1', ParamComp('x', val=60000.0), promotes=['*'])
        root.add('p2', ParamComp('y', val=60000.0), promotes=['*'])
        root.add('comp', Paraboloid(), promotes=['*'])
        root.add('constraint', ExecComp('con=f_xy + x + y'), promotes=['*'])

        driver.add_param('x', low=59000.0, high=61000.0, adder=-60000.0, scaler=1/1000.0)
        driver.add_objective('f_xy', adder=-10890367002.0, scaler=1.0/20)
        driver.add_constraint('con', adder=-10890487502.0, scaler=1.0/20)

        prob.setup(check=False)
        prob.run()

        self.assertEqual(driver.param_high, 1.0)
        self.assertEqual(driver.param_low, -1.0)
        self.assertEqual(driver.param, 0.0)
        self.assertEqual(prob['x'], 60500.0)
        self.assertEqual(driver.obj_scaled[0], 1.0)
        self.assertEqual(driver.con_scaled[0], 1.0)

    def test_scaler_adder_array(self):


        class ScaleAddDriver(Driver):

            def run(self, problem):
                """ Save away scaled info."""

                params = self.get_params()
                param_meta = self.get_param_metadata()

                self.set_param('x', np.array([22.0, 404.0, 9009.0, 121000.0]))
                problem.root.solve_nonlinear()

                objective = self.get_objectives()
                constraint = self.get_constraints()

                # Stuff we saved should be in the scaled coordinates.
                self.param = params['x']
                self.obj_scaled = objective['y']
                self.con_scaled = constraint['con']
                self.param_low = param_meta['x']['low']

        prob = Problem()
        root = prob.root = Group()
        driver = prob.driver = ScaleAddDriver()

        root.add('p1', ParamComp('x', val=np.array([[1.0, 1.0], [1.0, 1.0]])),
                 promotes=['*'])
        root.add('comp', ArrayComp2D(), promotes=['*'])
        root.add('constraint', ExecComp('con = x + y',
                                        x=np.array([[1.0, 1.0], [1.0, 1.0]]),
                                        y=np.array([[1.0, 1.0], [1.0, 1.0]]),
                                        con=np.array([[1.0, 1.0], [1.0, 1.0]])),
                 promotes=['*'])

        driver.add_param('x', low=np.array([[-1e5, -1e5], [-1e5, -1e5]]),
                         adder=np.array([[10.0, 100.0], [1000.0,10000.0]]),
                         scaler=np.array([[1.0, 2.0], [3.0, 4.0]]))
        driver.add_objective('y', adder=np.array([[10.0, 100.0], [1000.0,10000.0]]),
                         scaler=np.array([[1.0, 2.0], [3.0, 4.0]]))
        driver.add_constraint('con', adder=np.array([[10.0, 100.0], [1000.0,10000.0]]),
                              scaler=np.array([[1.0, 2.0], [3.0, 4.0]]))

        prob.setup(check=False)
        prob.run()

        self.assertEqual(driver.param[0], 11.0)
        self.assertEqual(driver.param[1], 202.0)
        self.assertEqual(driver.param[2], 3003.0)
        self.assertEqual(driver.param[3], 40004.0)
        self.assertEqual(prob['x'][0, 0], 12.0)
        self.assertEqual(prob['x'][0, 1], 102.0)
        self.assertEqual(prob['x'][1, 0], 2003.0)
        self.assertEqual(prob['x'][1, 1], 20250.0)
        self.assertEqual(driver.obj_scaled[0], (prob['y'][0, 0] + 10.0)*1.0)
        self.assertEqual(driver.obj_scaled[1], (prob['y'][0, 1] + 100.0)*2.0)
        self.assertEqual(driver.obj_scaled[2], (prob['y'][1, 0] + 1000.0)*3.0)
        self.assertEqual(driver.obj_scaled[3], (prob['y'][1, 1] + 10000.0)*4.0)
        self.assertEqual(driver.param_low[0], (-1e5 + 10.0)*1.0)
        self.assertEqual(driver.param_low[1], (-1e5 + 100.0)*2.0)
        self.assertEqual(driver.param_low[2], (-1e5 + 1000.0)*3.0)
        self.assertEqual(driver.param_low[3], (-1e5 + 10000.0)*4.0)
        conval = prob['x'] + prob['y']
        self.assertEqual(driver.con_scaled[0], (conval[0, 0] + 10.0)*1.0)
        self.assertEqual(driver.con_scaled[1], (conval[0, 1] + 100.0)*2.0)
        self.assertEqual(driver.con_scaled[2], (conval[1, 0] + 1000.0)*3.0)
        self.assertEqual(driver.con_scaled[3], (conval[1, 1] + 10000.0)*4.0)

    def test_eq_ineq_error_messages(self):

        prob = Problem()
        root = prob.root = SellarDerivatives()

        prob.driver = MySimpleDriver()

        # Don't try this at home, kids
        prob.driver.supports['Equality Constraints'] = False

        with self.assertRaises(RuntimeError) as cm:
            prob.driver.add_constraint('con1', ctype='eq')

        self.assertEquals(str(cm.exception), "Driver does not support equality constraint 'con1'.")

        # Don't try this at home, kids
        prob.driver.supports['Inequality Constraints'] = False

        with self.assertRaises(RuntimeError) as cm:
            prob.driver.add_constraint('con1', ctype='ineq')

        self.assertEquals(str(cm.exception), "Driver does not support inequality constraint 'con1'.")

if __name__ == "__main__":
    unittest.main()
