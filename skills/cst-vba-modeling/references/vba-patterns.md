# CST VBA History Patterns

Use these as structural patterns. Verify object names and methods against CST Macro Recorder output or the repository's offline CST references when uncertain.

## Parameter

```vb
StoreParameter "patch_w", "38.0"
StoreParameter "patch_l", "29.5"
```

Use the project's active geometry unit. Record the unit separately in the units history block.

## Material

```vb
With Material
    .Reset
    .Name "substrate_ro4003c"
    .Folder ""
    .Type "Normal"
    .Epsilon "3.55"
    .Mue "1.0"
    .TanD "0.0027"
    .Create
End With
```

## Brick

```vb
With Brick
    .Reset
    .Name "substrate"
    .Component "antenna"
    .Material "substrate_ro4003c"
    .Xrange "-sub_w/2", "sub_w/2"
    .Yrange "-sub_l/2", "sub_l/2"
    .Zrange "0", "sub_h"
    .Create
End With
```

## Boolean

```vb
Solid.Subtract "antenna:ground", "tool:slot"
```

Create tool solids in a dedicated component and delete or retain them intentionally. Confirm the first argument is the target.

## Transform

```vb
With Transform
    .Reset
    .Name "antenna:element"
    .Vector "dx", "0", "0"
    .UsePickedPoints "False"
    .InvertPickedPoints "False"
    .MultipleObjects "True"
    .GroupObjects "False"
    .Repetitions "3"
    .Transform "Shape", "Translate"
End With
```

## Review Checklist

- Every referenced component, solid, material, parameter, face, and port name is defined.
- Ranges have ordered minima/maxima and use the intended unit.
- Boolean target/tool order is correct.
- Ports touch the intended conductors and reference planes.
- Open boundaries and added space are appropriate for the frequency band.
- Required field or far-field monitors are created before the solve.
- The history title states the model change, not a generic label such as `macro`.
