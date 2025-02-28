""" Base class for linear and nonlinear solvers."""

from __future__ import print_function

from openmdao.core.options import OptionsDictionary

#public symbols
__all__ = ['LinearSolver', 'NonLinearSolver']


class SolverBase(object):
    """ Common base class for Linear and Nonlinear solver. Should not be used
    by users. Always inherit from one of the subclasses."""

    def __init__(self):
        self.iter_count = 0
        self.options = OptionsDictionary()
        desc = 'Set to 0 to disable printing, set to 1 to print the ' \
               'residual to stdout each iteration, set to 2 to print ' \
               'subiteration residuals as well.'
        self.options.add_option('iprint', 0, values=[0, 1, 2], desc=desc)
        self.recorders = []
        self.local_meta = None

    def print_norm(self, solver_string, metadata, iteration, res, res0,
                   msg=None, indent=0, solver='NL'):
        """ Prints out the norm of the residual in a neat readable format.

        Args
        ----
        solver_string: string
            Unique string to identify your solver type (e.g., 'LN_GS' or
            'NEWTON').

        metadata: dict
            OpenMDAO execution metadata containing iteration info.

        iteration: int
            Current iteration number

        res: float
            Absolute residual value.

        res0: float
            Baseline initial residual for relative comparison.

        msg: string, optional
            Message that indicates convergence.

        ident: int
            Additional indentation levels for subiterations.

        solver: string
            Solver type if not LN or NL (mostly for line search operations.)
        """
        name = metadata['name']

        # Find indentation level
        level = sum(len(item) for item in metadata['coord']
                    if not isinstance(item, str))
        # No indentation for driver; top solver is no indentation.
        level = level + indent - 2

        indent = '   ' * level
        if msg is not None:
            form = indent + '[%s] %s: %s   %d | %s'
            print(form % (name, solver, solver_string, iteration, msg))
            return

        form = indent + '[%s] %s: %s   %d | %.9g %.9g'
        print(form % (name, solver, solver_string, iteration, res, res/res0))


class LinearSolver(SolverBase):
    """ Base class for all linear solvers. Inherit from this class to create a
    new custom linear solver."""

    def add_recorder(self, recorder):
        """Appends the given recorder to this solver's list of recorders.

        Args
        ----
        recorder: `BaseRecorder`
            A recorder object.
        """
        self.recorders.append(recorder)

    def solve(self, rhs, system, mode):
        """ Solves the linear system for the problem in self.system. The
        full solution vector is returned. This function must be defined
        when inheriting.

        Args
        ----
        rhs : ndarray
            Array containing the right-hand side for the linear solve. Also
            possibly a 2D array with multiple right-hand sides.

        system : `System`
            Parent `System` object.

        mode : string
            Derivative mode, can be 'fwd' or 'rev'.

        Returns
        -------
        ndarray : Solution vector
        """
        pass


class NonLinearSolver(SolverBase):
    """ Base class for all nonlinear solvers. Inherit from this class to create a
    new custom nonlinear solver."""

    def add_recorder(self, recorder):
        """Appends the given recorder to this solver's list of recorders.

        Args
        ----
        recorder: `BaseRecorder`
            A recorder object.
        """
        self.recorders.append(recorder)

    def solve(self, params, unknowns, resids, system, metadata=None):
        """ Drive all residuals in self.system and all subsystems to zero.
        This includes all implicit components. This function must be defined
        when inheriting.

        Args
        ----
        params : `VecWrapper`
            `VecWrapper` containing parameters. (p)

        unknowns : `VecWrapper`
            `VecWrapper` containing outputs and states. (u)

        resids : `VecWrapper`
            `VecWrapper` containing residuals. (r)

        system : `System`
            Parent `System` object.

        metadata : dict, optional
            Dictionary containing execution metadata (e.g. iteration coordinate).
        """
        pass


