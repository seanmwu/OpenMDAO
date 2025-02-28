import sys

from six import string_types

from openmdao.recorders.baserecorder import BaseRecorder
from openmdao.util.recordutil import format_iteration_coordinate


class DumpCaseRecorder(BaseRecorder):
    """Dumps cases in a "pretty" form to `out`, which may be a string or a
    file-like object (defaults to ``stdout``). If `out` is ``stdout`` or
    ``stderr``, then that standard stream is used. Otherwise, if `out` is a
    string, then a file with that name will be opened in the current directory.
    If `out` is None, cases will be ignored.
    """

    def __init__(self, out='stdout'):
        super(DumpCaseRecorder, self).__init__()
        if isinstance(out, string_types):
            if out == 'stdout':
                out = sys.stdout
            elif out == 'stderr':
                out = sys.stderr
            else:
                out = open(out, 'w')
        self.out = out

    def startup(self, group):
        """ Write out info that applies to the entire run"""
        super(DumpCaseRecorder, self).startup(group)

    def record(self, params, unknowns, resids, metadata):
        """Dump the given run data in a "pretty" form."""
        if not self.out:  # if self.out is None, just do nothing
            return

        write = self.out.write
        write("Iteration Coordinate: {0:s}\n".format(format_iteration_coordinate(metadata['coord'])))

        write("Params:\n")
        for param, val in sorted(params.items()):
            write("  {0}: {1}\n".format(param, str(val)))

        write("Unknowns:\n")
        for unknown, val in sorted(unknowns.items()):
            write("  {0}: {1}\n".format(unknown, str(val)))

        write("Resids:\n")
        for resid, val in sorted(resids.items()):
            write("  {0}: {1}\n".format(resid, str(val)))
