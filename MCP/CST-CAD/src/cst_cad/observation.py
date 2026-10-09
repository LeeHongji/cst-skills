"""Pure readback macro and parser; CST execution belongs to a guarded worker."""
from typing import Any

VBA_TEMPLATE = """
Dim shapeCount As Long
Dim shapeIndex As Long
Dim shapeName As String
Dim xmin As Double, xmax As Double, ymin As Double, ymax As Double, zmin As Double, zmax As Double

Open "{output}" For Output As #7
shapeCount = Solid.GetNumberOfShapes
For shapeIndex = 0 To shapeCount - 1
    shapeName = Solid.GetNameOfShapeFromIndex(shapeIndex)
    Solid.GetLooseBoundingBoxOfShape shapeName, xmin, xmax, ymin, ymax, zmin, zmax
    Print #7, "SHAPE|" + shapeName + "|" + CStr(xmin) + "|" + CStr(xmax) + "|" + CStr(ymin) + "|" + CStr(ymax) + "|" + CStr(zmin) + "|" + CStr(zmax)
Next shapeIndex

Dim paramCount As Long
Dim paramIndex As Long
paramCount = GetNumberOfParameters
For paramIndex = 0 To paramCount - 1
    Print #7, "PARAM|" + GetParameterName(paramIndex) + "|" + CStr(GetParameterNValue(paramIndex))
Next paramIndex
Close #7
"""


def _number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def parse(payload: str) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    parameters: dict[str, float] = {}
    for line in payload.splitlines():
        parts = line.strip().split("|")
        if parts[0] == "SHAPE" and len(parts) == 8:
            component, _, name = parts[1].partition(":")
            entities.append(
                {
                    "component": component if name else "",
                    "name": name or component,
                    "bounding_box": {
                        "x0": _number(parts[2]),
                        "x1": _number(parts[3]),
                        "y0": _number(parts[4]),
                        "y1": _number(parts[5]),
                        "z0": _number(parts[6]),
                        "z1": _number(parts[7]),
                    },
                }
            )
        elif parts[0] == "PARAM" and len(parts) == 3:
            try:
                parameters[parts[1]] = _number(parts[2])
            except ValueError:
                continue
    return {"entities": entities, "parameters": parameters}

