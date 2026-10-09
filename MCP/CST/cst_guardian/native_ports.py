"""Documented port getters; observations never contain requested port values."""
import math
from pathlib import Path


def read_ports(model, directory):
    result = {}

    def query(name, method, call):
        try:
            value = call()
            result[name] = dict(value=value, method=method)
            return value
        except Exception as exc:
            result[name] = dict(error=str(exc))
            return None

    def count_ports():
        count = model.Solver.GetNumberOfPorts()
        if type(count) is not int or not 0 <= count <= 1024:
            raise ValueError('invalid native port count')
        return count

    count = query('ports.count', 'Solver.GetNumberOfPorts', count_ports)
    if count is None:
        return result
    if count == 0:
        result['ports'] = dict(value=[], method='Solver.GetNumberOfPorts: zero')
        return result

    directory = Path(directory)

    def consecutive_ports():
        # The Python bridge classifies the documented Are... query as History.
        # Execute only this fixed getter; never enable arbitrary History calls.
        target = directory/'port-numbering.txt'
        macro = '\n'.join(['Sub Main',
            f'Open "{str(target).replace(chr(34), chr(34)*2)}" For Output As #7',
            'Print #7, Solver.ArePortsSubsequentlyNamed', 'Close #7', 'End Sub'])
        target.with_suffix('.bas').write_text(macro, encoding='utf-8')
        if target.exists():
            raise ValueError('native port numbering output already exists')
        model._execute_vba_code(macro)
        value = target.read_text(encoding='utf-8-sig').strip().casefold()
        if value not in ('true', 'false'):
            raise ValueError('invalid native port numbering state')
        return value == 'true'

    consecutive = query('ports.consecutive', 'Solver.ArePortsSubsequentlyNamed', consecutive_ports)
    # A count does not establish port IDs when numbering has gaps. Do not
    # manufacture an inventory from requested IDs or call nonexistent ports.
    if consecutive is not True:
        return result
    for number in range(1, count + 1):
        prefix = f'ports.{number}.'
        query(prefix+'kind', 'Port.GetType',
              lambda: {'Waveguide': 'waveguide', 'Discrete': 'discrete'}[str(model.Port.GetType(number))])
        query(prefix+'label', 'Port.GetLabel', lambda: str(model.Port.GetLabel(number)))

        def modes():
            value = model.Port.GetNumberOfModes(number)
            if type(value) is not int or value < 1:
                raise ValueError('invalid native mode count')
            return value

        query(prefix+'modes', 'Port.GetNumberOfModes', modes)
        target = directory/f'port-{number}-center.txt'
        macro = '\n'.join([
            'Sub Main', 'Dim cx As Double, cy As Double, cz As Double',
            f'Port.GetPortCenterCoordinates {number}, cx, cy, cz',
            f'Open "{str(target).replace(chr(34), chr(34)*2)}" For Output As #7',
            'Print #7, cx', 'Print #7, cy', 'Print #7, cz', 'Close #7', 'End Sub'])
        # Keep the actual macro alongside native bytes, including on failure.
        target.with_suffix('.bas').write_text(macro, encoding='utf-8')
        try:
            if target.exists():
                raise ValueError('native port output already exists')
            model._execute_vba_code(macro)
            values = [float(v.replace(',', '.')) for v in target.read_text(encoding='utf-8-sig').splitlines()]
            if len(values) != 3 or not all(math.isfinite(v) for v in values):
                raise ValueError('incomplete or nonfinite native port center')
            for axis, value in zip('xyz', values):
                result[prefix+'center.'+axis] = dict(value=value, method='Port.GetPortCenterCoordinates')
        except Exception as exc:
            for axis in 'xyz':
                result[prefix+'center.'+axis] = dict(error=str(exc))
    return result
