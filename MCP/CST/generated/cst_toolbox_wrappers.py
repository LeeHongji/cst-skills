from __future__ import annotations

from typing import Any

from cst_runtime_cli_bridge import invoke_runtime_tool


def activate_post_process(*, project_path: str, operation: str, enable: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Activate or deactivate a post-processing operation."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['operation'] = operation
    args['enable'] = enable
    args.update(extra)
    return invoke_runtime_tool('activate-post-process', args, workspace=workspace, timeout_seconds=timeout_seconds)


def add_to_history(*, project_path: str, command: str, history_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Execute a raw VBA command via add_to_history for operations not covered by other tools."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['command'] = command
    args['history_name'] = history_name
    args.update(extra)
    return invoke_runtime_tool('add-to-history', args, workspace=workspace, timeout_seconds=timeout_seconds)


def analyze_probes(*, parameters: list[Any], probes: list[Any], workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Analyze probe results: compute main effects and two-way interactions. Input must include the parameter values and the objective value for each probe."""
    args: dict[str, Any] = {}
    args['parameters'] = parameters
    args['probes'] = probes
    args.update(extra)
    return invoke_runtime_tool('analyze-probes', args, workspace=workspace, timeout_seconds=timeout_seconds)


def ask_study(*, storage_path: str, study_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Ask the study for the next trial parameter suggestion."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args.update(extra)
    return invoke_runtime_tool('ask-study', args, workspace=workspace, timeout_seconds=timeout_seconds)


def best_study(*, storage_path: str, study_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Get current best result. For multi-objective returns Pareto front samples."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args.update(extra)
    return invoke_runtime_tool('best-study', args, workspace=workspace, timeout_seconds=timeout_seconds)


def boolean_add(*, project_path: str, shape1: str, shape2: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Unite two solids (boolean union)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['shape1'] = shape1
    args['shape2'] = shape2
    args.update(extra)
    return invoke_runtime_tool('boolean-add', args, workspace=workspace, timeout_seconds=timeout_seconds)


def boolean_insert(*, project_path: str, shape1: str, shape2: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Insert one solid into another (boolean insert)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['shape1'] = shape1
    args['shape2'] = shape2
    args.update(extra)
    return invoke_runtime_tool('boolean-insert', args, workspace=workspace, timeout_seconds=timeout_seconds)


def boolean_intersect(*, project_path: str, shape1: str, shape2: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Intersect two solids (boolean intersection)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['shape1'] = shape1
    args['shape2'] = shape2
    args.update(extra)
    return invoke_runtime_tool('boolean-intersect', args, workspace=workspace, timeout_seconds=timeout_seconds)


def boolean_subtract(*, project_path: str, target: str, tool: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Subtract one solid from another (boolean difference)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['target'] = target
    args['tool'] = tool
    args.update(extra)
    return invoke_runtime_tool('boolean-subtract', args, workspace=workspace, timeout_seconds=timeout_seconds)


def calculate_farfield_neighborhood_flatness(*, file_paths: list[Any], theta_max_deg: float, output_json: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Calculate near-boresight farfield cut flatness from exported cut JSON payloads."""
    args: dict[str, Any] = {}
    args['file_paths'] = file_paths
    args['theta_max_deg'] = theta_max_deg
    args['output_json'] = output_json
    args.update(extra)
    return invoke_runtime_tool('calculate-farfield-neighborhood-flatness', args, workspace=workspace, timeout_seconds=timeout_seconds)


def capture_3d_view(*, project_path: str, output_dir: str | None = None, filename_prefix: str | None = 'view', view_type: str | None = 'preset', preset_name: str | None = 'Isometric', azimuth: float | None = 45.0, elevation: float | None = 30.0, zoom: float | None = 1.0, return_image_data: bool | None = False, mode: str | None = 'save', close_after_capture: bool | None = True, image_width: int | None = 1920, image_height: int | None = 1080, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Capture 3D view(s) of CST model as PNG + JSON metadata. Single preset: capture one view. Comma-separated preset_name (e.g. 'Front,Top,Isometric') captures multiple angles in one session."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    if output_dir is not None:
        args['output_dir'] = output_dir
    if filename_prefix is not None:
        args['filename_prefix'] = filename_prefix
    if view_type is not None:
        args['view_type'] = view_type
    if preset_name is not None:
        args['preset_name'] = preset_name
    if azimuth is not None:
        args['azimuth'] = azimuth
    if elevation is not None:
        args['elevation'] = elevation
    if zoom is not None:
        args['zoom'] = zoom
    if return_image_data is not None:
        args['return_image_data'] = return_image_data
    if mode is not None:
        args['mode'] = mode
    if close_after_capture is not None:
        args['close_after_capture'] = close_after_capture
    if image_width is not None:
        args['image_width'] = image_width
    if image_height is not None:
        args['image_height'] = image_height
    args.update(extra)
    return invoke_runtime_tool('capture-3d-view', args, workspace=workspace, timeout_seconds=timeout_seconds)


def change_material(*, project_path: str, shape_name: str, material: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Change the material of a geometry entity. Use list-materials to see available names."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['shape_name'] = shape_name
    args['material'] = material
    args.update(extra)
    return invoke_runtime_tool('change-material', args, workspace=workspace, timeout_seconds=timeout_seconds)


def change_parameter(*, project_path: str, name: str, value: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Change one CST parameter in the verified working project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['value'] = value
    args.update(extra)
    return invoke_runtime_tool('change-parameter', args, workspace=workspace, timeout_seconds=timeout_seconds)


def change_solver_type(*, project_path: str, solver_type: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Change the CST solver type."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['solver_type'] = solver_type
    args.update(extra)
    return invoke_runtime_tool('change-solver-type', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_blank_project(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a new blank CST project at the specified path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('create-blank-project', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_component(*, project_path: str, component_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a new component in the CST project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['component_name'] = component_name
    args.update(extra)
    return invoke_runtime_tool('create-component', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_hollow_sweep(*, project_path: str, name: str, component: str, material: str, x_min1: int, x_max1: int, y_min1: int, y_max1: int, z1: int, x_min2: int, x_max2: int, y_min2: int, y_max2: int, z2: int, wall_thickness: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a hollow loft sweep with outer and inner walls."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['x_min1'] = x_min1
    args['x_max1'] = x_max1
    args['y_min1'] = y_min1
    args['y_max1'] = y_max1
    args['z1'] = z1
    args['x_min2'] = x_min2
    args['x_max2'] = x_max2
    args['y_min2'] = y_min2
    args['y_max2'] = y_max2
    args['z2'] = z2
    args['wall_thickness'] = wall_thickness
    args.update(extra)
    return invoke_runtime_tool('create-hollow-sweep', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_horn_segment(*, project_path: str, segment_id: int, bottom_radius: int, top_radius: int, z_min: int, z_max: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a horn segment (outer cone - inner cone)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['segment_id'] = segment_id
    args['bottom_radius'] = bottom_radius
    args['top_radius'] = top_radius
    args['z_min'] = z_min
    args['z_max'] = z_max
    args.update(extra)
    return invoke_runtime_tool('create-horn-segment', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_loft_sweep(*, project_path: str, name: str, component: str, material: str, x_min1: int, x_max1: int, y_min1: int, y_max1: int, z1: int, x_min2: int, x_max2: int, y_min2: int, y_max2: int, z2: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a loft sweep between two 2D profiles in one step."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['x_min1'] = x_min1
    args['x_max1'] = x_max1
    args['y_min1'] = y_min1
    args['y_max1'] = y_max1
    args['z1'] = z1
    args['x_min2'] = x_min2
    args['x_max2'] = x_max2
    args['y_min2'] = y_min2
    args['y_max2'] = y_max2
    args['z2'] = z2
    args.update(extra)
    return invoke_runtime_tool('create-loft-sweep', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_mesh_group(*, project_path: str, group_name: str, items: list[Any], workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a mesh group and add items."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['group_name'] = group_name
    args['items'] = items
    args.update(extra)
    return invoke_runtime_tool('create-mesh-group', args, workspace=workspace, timeout_seconds=timeout_seconds)


def create_study(*, storage_path: str, study_name: str, parameters: str, direction: str, directions: list[Any], value_names: list[Any], constraints: list[Any], sampler: str, n_startup_trials: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create or load an Optuna optimization study. Supports single-objective, multi-objective (directions), and constraint-enabled studies."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args['parameters'] = parameters
    args['direction'] = direction
    args['directions'] = directions
    args['value_names'] = value_names
    args['constraints'] = constraints
    args['sampler'] = sampler
    args['n_startup_trials'] = n_startup_trials
    args.update(extra)
    return invoke_runtime_tool('create-study', args, workspace=workspace, timeout_seconds=timeout_seconds)


def cst_session_close(*, project_path: str, save: bool, wait_unlock: bool, timeout_seconds_: int, poll_interval_seconds: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Close the expected CST project, optionally wait for locks to clear, then inspect the environment."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['save'] = save
    args['wait_unlock'] = wait_unlock
    args['timeout_seconds'] = timeout_seconds_
    args['poll_interval_seconds'] = poll_interval_seconds
    args.update(extra)
    return invoke_runtime_tool('cst-session-close', args, workspace=workspace, timeout_seconds=timeout_seconds)


def cst_session_inspect(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Central session/process gate: inspect processes, locks, open projects, and reattach readiness."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('cst-session-inspect', args, workspace=workspace, timeout_seconds=timeout_seconds)


def cst_session_open(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Open a CST project through the central session manager and inspect the environment afterward."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('cst-session-open', args, workspace=workspace, timeout_seconds=timeout_seconds)


def cst_session_quit(*, project_path: str, dry_run: bool, settle_seconds: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Quit CST through the central session manager using only the process allowlist and lock evidence."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['dry_run'] = dry_run
    args['settle_seconds'] = settle_seconds
    args.update(extra)
    return invoke_runtime_tool('cst-session-quit', args, workspace=workspace, timeout_seconds=timeout_seconds)


def cst_session_reattach(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Reattach to the expected CST project only if it is the sole open project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('cst-session-reattach', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_analytical_curve(*, project_path: str, name: str, curve: str, law_x: str, law_y: str, law_z: str, param_start: str, param_end: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Define an analytical curve using parametric equations."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['curve'] = curve
    args['law_x'] = law_x
    args['law_y'] = law_y
    args['law_z'] = law_z
    args['param_start'] = param_start
    args['param_end'] = param_end
    args.update(extra)
    return invoke_runtime_tool('define-analytical-curve', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_background(*, project_path: str, background_type: str | None = 'Normal', workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set the background type (Normal or PEC)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    if background_type is not None:
        args['background_type'] = background_type
    args.update(extra)
    return invoke_runtime_tool('define-background', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_boundary(*, project_path: str, face_type: str | None = 'expanded open', symmetry_type: str | None = 'none', workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set boundary conditions for all faces and symmetries."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    if face_type is not None:
        args['face_type'] = face_type
    if symmetry_type is not None:
        args['symmetry_type'] = symmetry_type
    args.update(extra)
    return invoke_runtime_tool('define-boundary', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_brick(*, project_path: str, name: str, component: str, material: str, x_min: int, x_max: int, y_min: int, y_max: int, z_min: int, z_max: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a rectangular brick in the CST project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['x_min'] = x_min
    args['x_max'] = x_max
    args['y_min'] = y_min
    args['y_max'] = y_max
    args['z_min'] = z_min
    args['z_max'] = z_max
    args.update(extra)
    return invoke_runtime_tool('define-brick', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_cone(*, project_path: str, name: str, component: str, material: str, bottom_radius: int, top_radius: int, axis: str, z_min: int, z_max: int, x_center: int, y_center: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a cone in the CST project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['bottom_radius'] = bottom_radius
    args['top_radius'] = top_radius
    args['axis'] = axis
    args['z_min'] = z_min
    args['z_max'] = z_max
    args['x_center'] = x_center
    args['y_center'] = y_center
    args.update(extra)
    return invoke_runtime_tool('define-cone', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_cylinder(*, project_path: str, name: str, component: str, material: str, outer_radius: int, inner_radius: int, axis: str, z_min: int, z_max: int, x_center: int, y_center: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a cylinder in the CST project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['outer_radius'] = outer_radius
    args['inner_radius'] = inner_radius
    args['axis'] = axis
    args['z_min'] = z_min
    args['z_max'] = z_max
    args['x_center'] = x_center
    args['y_center'] = y_center
    args.update(extra)
    return invoke_runtime_tool('define-cylinder', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_extrude_curve(*, project_path: str, name: str, component: str, material: str, curve: str, thickness: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Extrude a curve profile into a solid."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['curve'] = curve
    args['thickness'] = thickness
    args.update(extra)
    return invoke_runtime_tool('define-extrude-curve', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_frequency_range(*, project_path: str, start_freq: float, end_freq: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set the simulation frequency range."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['start_freq'] = start_freq
    args['end_freq'] = end_freq
    args.update(extra)
    return invoke_runtime_tool('define-frequency-range', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_loft(*, project_path: str, name: str, component: str, material: str, tangency: int, minimize_twist: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Execute a loft between pre-picked faces."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['component'] = component
    args['material'] = material
    args['tangency'] = tangency
    args['minimize_twist'] = minimize_twist
    args.update(extra)
    return invoke_runtime_tool('define-loft', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_material_from_mtd(*, project_path: str, material_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Define a CST material from .mtd file by material name. Material must exist in references/Materials/. Use list-materials to see available names."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['material_name'] = material_name
    args.update(extra)
    return invoke_runtime_tool('define-material-from-mtd', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_mesh(*, project_path: str, steps_per_wave_near: float, steps_per_wave_far: float, steps_per_box_near: float, steps_per_box_far: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Configure the hexahedral mesh parameters."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['steps_per_wave_near'] = steps_per_wave_near
    args['steps_per_wave_far'] = steps_per_wave_far
    args['steps_per_box_near'] = steps_per_box_near
    args['steps_per_box_far'] = steps_per_box_far
    args.update(extra)
    return invoke_runtime_tool('define-mesh', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_monitor(*, project_path: str, start_freq: float, end_freq: float, step: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Define a farfield monitor over a frequency range."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['start_freq'] = start_freq
    args['end_freq'] = end_freq
    args['step'] = step
    args.update(extra)
    return invoke_runtime_tool('define-monitor', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_parameters(*, project_path: str, names: list[Any], values: list[Any], workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Batch-define multiple CST parameters using StoreParameters."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['names'] = names
    args['values'] = values
    args.update(extra)
    return invoke_runtime_tool('define-parameters', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_polygon_3d(*, project_path: str, name: str, curve: str, points: list[Any], workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Define a 3D polygon curve from a list of points."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['curve'] = curve
    args['points'] = points
    args.update(extra)
    return invoke_runtime_tool('define-polygon-3d', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_port(*, project_path: str, port_number: str, x_min: float, x_max: float, y_min: float, y_max: float, z_min: float, z_max: float, orientation: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Define a waveguide port."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['port_number'] = port_number
    args['x_min'] = x_min
    args['x_max'] = x_max
    args['y_min'] = y_min
    args['y_max'] = y_max
    args['z_min'] = z_min
    args['z_max'] = z_max
    args['orientation'] = orientation
    args.update(extra)
    return invoke_runtime_tool('define-port', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_rectangle(*, project_path: str, name: str, curve: str, x_min: int, x_max: int, y_min: int, y_max: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a 2D rectangle on a curve in the CST project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['name'] = name
    args['curve'] = curve
    args['x_min'] = x_min
    args['x_max'] = x_max
    args['y_min'] = y_min
    args['y_max'] = y_max
    args.update(extra)
    return invoke_runtime_tool('define-rectangle', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_solver(*, project_path: str, stimulation_port: str, steady_state_limit: float, norming_impedance: float, stimulation_mode: str | None = 'All', mesh_adaption: bool | None = False, auto_norm_impedance: bool | None = True, calculate_modes_only: bool | None = False, s_para_symmetry: bool | None = False, store_td_results: bool | None = False, run_discretizer_only: bool | None = False, full_deembedding: bool | None = False, superimpose_plw: bool | None = False, use_sensitivity: bool | None = False, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Configure the time-domain solver settings."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['stimulation_port'] = stimulation_port
    if stimulation_mode is not None:
        args['stimulation_mode'] = stimulation_mode
    args['steady_state_limit'] = steady_state_limit
    args['norming_impedance'] = norming_impedance
    if mesh_adaption is not None:
        args['mesh_adaption'] = mesh_adaption
    if auto_norm_impedance is not None:
        args['auto_norm_impedance'] = auto_norm_impedance
    if calculate_modes_only is not None:
        args['calculate_modes_only'] = calculate_modes_only
    if s_para_symmetry is not None:
        args['s_para_symmetry'] = s_para_symmetry
    if store_td_results is not None:
        args['store_td_results'] = store_td_results
    if run_discretizer_only is not None:
        args['run_discretizer_only'] = run_discretizer_only
    if full_deembedding is not None:
        args['full_deembedding'] = full_deembedding
    if superimpose_plw is not None:
        args['superimpose_plw'] = superimpose_plw
    if use_sensitivity is not None:
        args['use_sensitivity'] = use_sensitivity
    args.update(extra)
    return invoke_runtime_tool('define-solver', args, workspace=workspace, timeout_seconds=timeout_seconds)


def define_units(*, project_path: str, length: str, frequency: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set the CST project unit system."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['length'] = length
    args['frequency'] = frequency
    args.update(extra)
    return invoke_runtime_tool('define-units', args, workspace=workspace, timeout_seconds=timeout_seconds)


def delete_entity(*, project_path: str, component: str, name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Delete a geometry entity from the CST project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['component'] = component
    args['name'] = name
    args.update(extra)
    return invoke_runtime_tool('delete-entity', args, workspace=workspace, timeout_seconds=timeout_seconds)


def delete_monitor(*, project_path: str, monitor_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Delete a monitor by name."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['monitor_name'] = monitor_name
    args.update(extra)
    return invoke_runtime_tool('delete-monitor', args, workspace=workspace, timeout_seconds=timeout_seconds)


def delete_probe(*, project_path: str, probe_id: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Delete a probe by its ID."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['probe_id'] = probe_id
    args.update(extra)
    return invoke_runtime_tool('delete-probe', args, workspace=workspace, timeout_seconds=timeout_seconds)


def design_probes(*, parameters: dict[str, Any], max_probes: int, include_center: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Design a Plackett-Burman probe plan to screen parameters. Returns a list of experiments; run each via prepare-experiment + run-experiment, then feed results to analyze-probes."""
    args: dict[str, Any] = {}
    args['parameters'] = parameters
    args['max_probes'] = max_probes
    args['include_center'] = include_center
    args.update(extra)
    return invoke_runtime_tool('design-probes', args, workspace=workspace, timeout_seconds=timeout_seconds)


def export_e_field(*, project_path: str, frequency: str, file_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export E-field data at a given frequency to ASCII."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['frequency'] = frequency
    args['file_path'] = file_path
    args.update(extra)
    return invoke_runtime_tool('export-e-field', args, workspace=workspace, timeout_seconds=timeout_seconds)


def export_farfield_cut(*, project_path: str, tree_path: str, export_dir: str, fresh_session: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export an existing CST Farfield Cut tree item to JSON under {export_dir}/farfield/cuts/."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['tree_path'] = tree_path
    args['export_dir'] = export_dir
    args['fresh_session'] = fresh_session
    args.update(extra)
    return invoke_runtime_tool('export-farfield-cut', args, workspace=workspace, timeout_seconds=timeout_seconds)


def export_farfield_grid(*, project_path: str, farfield_name: str, export_dir: str, quantity: str, theta_step_deg: float, phi_step_deg: float, theta_min_deg: float, theta_max_deg: float, phi_min_deg: float, phi_max_deg: float, run_id: str, fresh_session: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Compute a FarfieldCalculator scalar grid and export as JSON under {export_dir}/farfield/. Supports fresh_session reuse."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['farfield_name'] = farfield_name
    args['export_dir'] = export_dir
    args['quantity'] = quantity
    args['theta_step_deg'] = theta_step_deg
    args['phi_step_deg'] = phi_step_deg
    args['theta_min_deg'] = theta_min_deg
    args['theta_max_deg'] = theta_max_deg
    args['phi_min_deg'] = phi_min_deg
    args['phi_max_deg'] = phi_max_deg
    args['run_id'] = run_id
    args['fresh_session'] = fresh_session
    args.update(extra)
    return invoke_runtime_tool('export-farfield-grid', args, workspace=workspace, timeout_seconds=timeout_seconds)


def export_run_results(*, project_path: str, farfield_names: list[Any], farfield_plot_mode: str, farfield_theta_step: float, farfield_phi_step: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export S11, 2D, and farfield results to the exports directory after simulation."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['farfield_names'] = farfield_names
    args['farfield_plot_mode'] = farfield_plot_mode
    args['farfield_theta_step'] = farfield_theta_step
    args['farfield_phi_step'] = farfield_phi_step
    args.update(extra)
    return invoke_runtime_tool('export-run-results', args, workspace=workspace, timeout_seconds=timeout_seconds)


def export_surface_current(*, project_path: str, frequency: str, file_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export surface current data at a given frequency to ASCII."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['frequency'] = frequency
    args['file_path'] = file_path
    args.update(extra)
    return invoke_runtime_tool('export-surface-current', args, workspace=workspace, timeout_seconds=timeout_seconds)


def export_voltage(*, project_path: str, voltage_index: str, file_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export voltage monitor data to ASCII."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['voltage_index'] = voltage_index
    args['file_path'] = file_path
    args.update(extra)
    return invoke_runtime_tool('export-voltage', args, workspace=workspace, timeout_seconds=timeout_seconds)


def generate_report(*, data_dir: str, output_html: str, page_title: str, modules: str, split: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Generate a modular HTML report from exported S11, farfield, and audit files. Supports --modules and --split."""
    args: dict[str, Any] = {}
    args['data_dir'] = data_dir
    args['output_html'] = output_html
    args['page_title'] = page_title
    args['modules'] = modules
    args['split'] = split
    args.update(extra)
    return invoke_runtime_tool('generate-report', args, workspace=workspace, timeout_seconds=timeout_seconds)


def get_1d_result(*, project_path: str, treepath: str, module_type: str, run_id: int, load_impedances: bool, export_path: str, allow_interactive: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export a 0D/1D result item to JSON from a project path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['treepath'] = treepath
    args['module_type'] = module_type
    args['run_id'] = run_id
    args['load_impedances'] = load_impedances
    args['export_path'] = export_path
    args['allow_interactive'] = allow_interactive
    args.update(extra)
    return invoke_runtime_tool('get-1d-result', args, workspace=workspace, timeout_seconds=timeout_seconds)


def get_2d_result(*, project_path: str, treepath: str, module_type: str, export_path: str, allow_interactive: bool, subproject_treepath: str, include_data: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Export a 2D result item to JSON from a project path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['treepath'] = treepath
    args['module_type'] = module_type
    args['export_path'] = export_path
    args['allow_interactive'] = allow_interactive
    args['subproject_treepath'] = subproject_treepath
    args['include_data'] = include_data
    args.update(extra)
    return invoke_runtime_tool('get-2d-result', args, workspace=workspace, timeout_seconds=timeout_seconds)


def get_parameter_combination(*, project_path: str, run_id: int, module_type: str, allow_interactive: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Read the parameter combination for a result run ID."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['run_id'] = run_id
    args['module_type'] = module_type
    args['allow_interactive'] = allow_interactive
    args.update(extra)
    return invoke_runtime_tool('get-parameter-combination', args, workspace=workspace, timeout_seconds=timeout_seconds)


def get_run_context(*, task_path: str, run_id: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Read standard run context through cst_runtime."""
    args: dict[str, Any] = {}
    args['task_path'] = task_path
    args['run_id'] = run_id
    args.update(extra)
    return invoke_runtime_tool('get-run-context', args, workspace=workspace, timeout_seconds=timeout_seconds)


def get_version_info(*, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Read cst.results version information."""
    args: dict[str, Any] = {}
    args.update(extra)
    return invoke_runtime_tool('get-version-info', args, workspace=workspace, timeout_seconds=timeout_seconds)


def health_check(*, workspace_: str, auto_fix: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Run comprehensive environment diagnostics: Python, uv, workspace, CST libraries, imports. Auto-fixes what it can, reports remaining issues with user instructions."""
    args: dict[str, Any] = {}
    args['workspace'] = workspace_
    args['auto_fix'] = auto_fix
    args.update(extra)
    return invoke_runtime_tool('health-check', args, workspace=workspace, timeout_seconds=timeout_seconds)


def infer_run_dir(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Infer run_dir from a projects/working.cst project path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('infer-run-dir', args, workspace=workspace, timeout_seconds=timeout_seconds)


def init_task(*, workspace_: str, task_id: str, source_project: str, goal: str, title: str, force: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a task.json and runs directory inside a runtime workspace."""
    args: dict[str, Any] = {}
    args['workspace'] = workspace_
    args['task_id'] = task_id
    args['source_project'] = source_project
    args['goal'] = goal
    args['title'] = title
    args['force'] = force
    args.update(extra)
    return invoke_runtime_tool('init-task', args, workspace=workspace, timeout_seconds=timeout_seconds)


def init_workspace(*, workspace_: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Initialize a minimal CST runtime workspace in an empty or existing directory."""
    args: dict[str, Any] = {}
    args['workspace'] = workspace_
    args.update(extra)
    return invoke_runtime_tool('init-workspace', args, workspace=workspace, timeout_seconds=timeout_seconds)


def inspect_farfield_monitors(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Discover farfield monitors from a CST project by scanning the result tree."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('inspect-farfield-monitors', args, workspace=workspace, timeout_seconds=timeout_seconds)


def inspect_project(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Open a CST project, list all parameters and entities, then close. Returns parameter names/values and entity names."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('inspect-project', args, workspace=workspace, timeout_seconds=timeout_seconds)


def install_cst_libraries(*, cst_path: str, dry_run: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Install or verify CST Python libraries (cst, cst.results, cst.interface) using the uv-managed environment."""
    args: dict[str, Any] = {}
    args['cst_path'] = cst_path
    args['dry_run'] = dry_run
    args.update(extra)
    return invoke_runtime_tool('install-cst-libraries', args, workspace=workspace, timeout_seconds=timeout_seconds)


def is_simulation_running(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Check whether the CST solver is currently running for the verified working project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('is-simulation-running', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_entities(*, project_path: str, component: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List geometry entities from the verified CST working project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['component'] = component
    args.update(extra)
    return invoke_runtime_tool('list-entities', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_materials(*, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List available CST material names from the Materials library."""
    args: dict[str, Any] = {}
    args.update(extra)
    return invoke_runtime_tool('list-materials', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_open_projects(*, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List CST projects visible through DesignEnvironment.connect_to_any()."""
    args: dict[str, Any] = {}
    args.update(extra)
    return invoke_runtime_tool('list-open-projects', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_parameters(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List parameters from the verified CST working project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('list-parameters', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_result_items(*, project_path: str, module_type: str, filter_type: str, allow_interactive: bool, subproject_treepath: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List result tree items from a project path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['module_type'] = module_type
    args['filter_type'] = filter_type
    args['allow_interactive'] = allow_interactive
    args['subproject_treepath'] = subproject_treepath
    args.update(extra)
    return invoke_runtime_tool('list-result-items', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_run_ids(*, project_path: str, treepath: str, module_type: str, allow_interactive: bool, skip_nonparametric: bool, max_mesh_passes_only: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List CST result run IDs from a project path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['treepath'] = treepath
    args['module_type'] = module_type
    args['allow_interactive'] = allow_interactive
    args['skip_nonparametric'] = skip_nonparametric
    args['max_mesh_passes_only'] = max_mesh_passes_only
    args.update(extra)
    return invoke_runtime_tool('list-run-ids', args, workspace=workspace, timeout_seconds=timeout_seconds)


def list_subprojects(*, project_path: str, allow_interactive: bool, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """List subprojects from a CST results project by explicit project_path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['allow_interactive'] = allow_interactive
    args.update(extra)
    return invoke_runtime_tool('list-subprojects', args, workspace=workspace, timeout_seconds=timeout_seconds)


def open_results_project(*, project_path: str, allow_interactive: bool, subproject_treepath: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Validate that cst.results can open a project path."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['allow_interactive'] = allow_interactive
    args['subproject_treepath'] = subproject_treepath
    args.update(extra)
    return invoke_runtime_tool('open-results-project', args, workspace=workspace, timeout_seconds=timeout_seconds)


def pause_simulation(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Pause the currently running CST solver."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('pause-simulation', args, workspace=workspace, timeout_seconds=timeout_seconds)


def pick_face(*, project_path: str, component: str, name: str, face_id: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Select a face by ID for loft operations (zero-thickness entities only)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['component'] = component
    args['name'] = name
    args['face_id'] = face_id
    args.update(extra)
    return invoke_runtime_tool('pick-face', args, workspace=workspace, timeout_seconds=timeout_seconds)


def plot_exported_file(*, file_path: str, output_html: str, page_title: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Render an exported JSON result or CST farfield ASCII/TXT file to an HTML preview."""
    args: dict[str, Any] = {}
    args['file_path'] = file_path
    args['output_html'] = output_html
    args['page_title'] = page_title
    args.update(extra)
    return invoke_runtime_tool('plot-exported-file', args, workspace=workspace, timeout_seconds=timeout_seconds)


def prepare_experiment(*, project_path: str, param_name: str, param_value: float, names: list[Any], values: list[Any], workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Open a CST project, change one or more parameters, confirm, then save and close. Supports batch via names+values arrays. Use before run-experiment."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['param_name'] = param_name
    args['param_value'] = param_value
    args['names'] = names
    args['values'] = values
    args.update(extra)
    return invoke_runtime_tool('prepare-experiment', args, workspace=workspace, timeout_seconds=timeout_seconds)


def prepare_run(*, task_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Create a standard run workspace through cst_runtime."""
    args: dict[str, Any] = {}
    args['task_path'] = task_path
    args.update(extra)
    return invoke_runtime_tool('prepare-run', args, workspace=workspace, timeout_seconds=timeout_seconds)


def record_stage(*, task_path: str, run_id: str, stage: str, status: str, message: str, details_json: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Write a stage record and production-chain log entry."""
    args: dict[str, Any] = {}
    args['task_path'] = task_path
    args['run_id'] = run_id
    args['stage'] = stage
    args['status'] = status
    args['message'] = message
    args['details_json'] = details_json
    args.update(extra)
    return invoke_runtime_tool('record-stage', args, workspace=workspace, timeout_seconds=timeout_seconds)


def rename_entity(*, project_path: str, old_name: str, new_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Rename a geometry entity."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['old_name'] = old_name
    args['new_name'] = new_name
    args.update(extra)
    return invoke_runtime_tool('rename-entity', args, workspace=workspace, timeout_seconds=timeout_seconds)


def resume_simulation(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Resume a paused CST solver."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('resume-simulation', args, workspace=workspace, timeout_seconds=timeout_seconds)


def run_experiment(*, project_path: str, farfield_names: list[Any], farfield_plot_mode: str, farfield_theta_step: float, farfield_phi_step: float, timeout_seconds_: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Run a simulation, wait for completion, and export S11 + farfield results. Returns s11_metric with min_db and best_freq."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['farfield_names'] = farfield_names
    args['farfield_plot_mode'] = farfield_plot_mode
    args['farfield_theta_step'] = farfield_theta_step
    args['farfield_phi_step'] = farfield_phi_step
    args['timeout_seconds'] = timeout_seconds_
    args.update(extra)
    return invoke_runtime_tool('run-experiment', args, workspace=workspace, timeout_seconds=timeout_seconds)


def run_optimization_step(*, project_path: str, study_storage: str, study_name: str, objective: dict[str, Any] | None = {'type': 's11_min_db'}, sampler: str | None = None, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Run one optimization iteration: ask Optuna for next parameters, apply them, simulate, compute objective, and report back. Agent inspects the objective_value output to decide whether to stop or continue the loop."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['study_storage'] = study_storage
    args['study_name'] = study_name
    if objective is not None:
        args['objective'] = objective
    if sampler is not None:
        args['sampler'] = sampler
    args.update(extra)
    return invoke_runtime_tool('run-optimization-step', args, workspace=workspace, timeout_seconds=timeout_seconds)


def run_probe_phase(*, project_path: str, parameters: dict[str, Any], study_storage: str, study_name: str, max_probes: int | None = 12, include_center: bool | None = True, objective: dict[str, Any] | None = {'type': 's11_min_db'}, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Run the complete probe phase: design Plackett-Burman probes, simulate each, analyze main effects and interactions, then inject results into an Optuna study. The working.cst is copied to working_probe.cst for isolation; exports go to exports/probe/. Returns top_params, edge_hit, and suggested_algorithm. Supports objective parameter to customize the objective function (default: s11_min_db)."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['parameters'] = parameters
    args['study_storage'] = study_storage
    args['study_name'] = study_name
    if max_probes is not None:
        args['max_probes'] = max_probes
    if include_center is not None:
        args['include_center'] = include_center
    if objective is not None:
        args['objective'] = objective
    args.update(extra)
    return invoke_runtime_tool('run-probe-phase', args, workspace=workspace, timeout_seconds=timeout_seconds)


def save_project(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Save the verified CST working project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('save-project', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_background_with_space(*, project_path: str, x_min_space: float | None = 30, x_max_space: float | None = 30, y_min_space: float | None = 30, y_max_space: float | None = 30, z_min_space: float | None = 50, z_max_space: float | None = 100, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set background space distances on all six sides."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    if x_min_space is not None:
        args['x_min_space'] = x_min_space
    if x_max_space is not None:
        args['x_max_space'] = x_max_space
    if y_min_space is not None:
        args['y_min_space'] = y_min_space
    if y_max_space is not None:
        args['y_max_space'] = y_max_space
    if z_min_space is not None:
        args['z_min_space'] = z_min_space
    if z_max_space is not None:
        args['z_max_space'] = z_max_space
    args.update(extra)
    return invoke_runtime_tool('set-background-with-space', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_efield_monitor(*, project_path: str, start_freq: float, end_freq: float, step: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set an E-field monitor over a frequency range."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['start_freq'] = start_freq
    args['end_freq'] = end_freq
    args['step'] = step
    args.update(extra)
    return invoke_runtime_tool('set-efield-monitor', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_entity_color(*, project_path: str, shape_name: str, r: int, g: int, b: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set the display color of a geometry entity."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['shape_name'] = shape_name
    args['r'] = r
    args['g'] = g
    args['b'] = b
    args.update(extra)
    return invoke_runtime_tool('set-entity-color', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_farfield_monitor(*, project_path: str, start_freq: float, end_freq: float, step: int, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set a farfield monitor over a frequency range."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['start_freq'] = start_freq
    args['end_freq'] = end_freq
    args['step'] = step
    args.update(extra)
    return invoke_runtime_tool('set-farfield-monitor', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_farfield_plot_cuts(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set farfield plot cut angles."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('set-farfield-plot-cuts', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_fdsolver_extrude_open_bc(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Enable or disable FD solver extruded open boundary."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('set-fdsolver-extrude-open-bc', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_field_monitor(*, project_path: str, field_type: str, start_frequency: str, end_frequency: str, num_samples: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set a field monitor (e.g. H-field) over a frequency range."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['field_type'] = field_type
    args['start_frequency'] = start_frequency
    args['end_frequency'] = end_frequency
    args['num_samples'] = num_samples
    args.update(extra)
    return invoke_runtime_tool('set-field-monitor', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_mesh_fpbavoid_nonreg_unite(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Enable or disable mesh FPBA non-regular unite avoidance."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('set-mesh-fpbavoid-nonreg-unite', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_mesh_minimum_step_number(*, project_path: str, num_steps: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set the minimum mesh step number."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['num_steps'] = num_steps
    args.update(extra)
    return invoke_runtime_tool('set-mesh-minimum-step-number', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_probe(*, project_path: str, field_type: str, x_pos: str, y_pos: str, z_pos: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Set a field probe at a specified position."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['field_type'] = field_type
    args['x_pos'] = x_pos
    args['y_pos'] = y_pos
    args['z_pos'] = z_pos
    args.update(extra)
    return invoke_runtime_tool('set-probe', args, workspace=workspace, timeout_seconds=timeout_seconds)


def set_solver_acceleration(*, project_path: str, use_parallelization: bool, max_threads: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Configure solver parallelization and hardware acceleration."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['use_parallelization'] = use_parallelization
    args['max_threads'] = max_threads
    args.update(extra)
    return invoke_runtime_tool('set-solver-acceleration', args, workspace=workspace, timeout_seconds=timeout_seconds)


def show_bounding_box(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Toggle bounding box display."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('show-bounding-box', args, workspace=workspace, timeout_seconds=timeout_seconds)


def stage_evidence(*, project_path: str, capture: list[Any], stage_name: str, output_dir: str, compare: list[Any], output_html: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Capture CST project state snapshots and generate before/after comparison reports. Use --capture to snapshot, --compare to diff two snapshots into HTML."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['capture'] = capture
    args['stage_name'] = stage_name
    args['output_dir'] = output_dir
    args['compare'] = compare
    args['output_html'] = output_html
    args.update(extra)
    return invoke_runtime_tool('stage-evidence', args, workspace=workspace, timeout_seconds=timeout_seconds)


def start_simulation_async(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Start the CST solver asynchronously for the verified working project."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('start-simulation-async', args, workspace=workspace, timeout_seconds=timeout_seconds)


def stop_simulation(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Stop the currently running CST solver."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('stop-simulation', args, workspace=workspace, timeout_seconds=timeout_seconds)


def study_add_trials(*, storage_path: str, study_name: str, trials: list[Any], workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Inject pre-computed trials (e.g. from manual grid scan) into a study. Each trial: {params, values, constraints?}."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args['trials'] = trials
    args.update(extra)
    return invoke_runtime_tool('study-add-trials', args, workspace=workspace, timeout_seconds=timeout_seconds)


def study_param_importances(*, storage_path: str, study_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Analyze which parameters most affect the objective. Requires at least 5 completed trials."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args.update(extra)
    return invoke_runtime_tool('study-param-importances', args, workspace=workspace, timeout_seconds=timeout_seconds)


def study_terminate_check(*, storage_path: str, study_name: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Check if optimization has converged using Optuna's regret-bound evaluator. Returns should_terminate."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args.update(extra)
    return invoke_runtime_tool('study-terminate-check', args, workspace=workspace, timeout_seconds=timeout_seconds)


def tell_study(*, storage_path: str, study_name: str, trial_number: int, value: float, values: list[Any], constraints: list[Any], state: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Report trial result. Supports single value, multi-objective values array, and optional constraints."""
    args: dict[str, Any] = {}
    args['storage_path'] = storage_path
    args['study_name'] = study_name
    args['trial_number'] = trial_number
    args['value'] = value
    args['values'] = values
    args['constraints'] = constraints
    args['state'] = state
    args.update(extra)
    return invoke_runtime_tool('tell-study', args, workspace=workspace, timeout_seconds=timeout_seconds)


def transform_curve(*, project_path: str, curve_name: str, center_x: str, center_y: str, center_z: str, plane_normal_x: str, plane_normal_y: str, plane_normal_z: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Mirror a curve."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['curve_name'] = curve_name
    args['center_x'] = center_x
    args['center_y'] = center_y
    args['center_z'] = center_z
    args['plane_normal_x'] = plane_normal_x
    args['plane_normal_y'] = plane_normal_y
    args['plane_normal_z'] = plane_normal_z
    args.update(extra)
    return invoke_runtime_tool('transform-curve', args, workspace=workspace, timeout_seconds=timeout_seconds)


def transform_shape(*, project_path: str, shape_name: str, transform_type: str, center_x: str, center_y: str, center_z: str, plane_normal_x: str, plane_normal_y: str, plane_normal_z: str, angle_x: str | None = '0', angle_y: str | None = '0', angle_z: str | None = '0', multiple_objects: bool | None = True, group_objects: bool | None = False, repetitions: int | None = 1, destination: str | None = '', workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Mirror or rotate a geometry shape."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['shape_name'] = shape_name
    args['transform_type'] = transform_type
    args['center_x'] = center_x
    args['center_y'] = center_y
    args['center_z'] = center_z
    args['plane_normal_x'] = plane_normal_x
    args['plane_normal_y'] = plane_normal_y
    args['plane_normal_z'] = plane_normal_z
    if angle_x is not None:
        args['angle_x'] = angle_x
    if angle_y is not None:
        args['angle_y'] = angle_y
    if angle_z is not None:
        args['angle_z'] = angle_z
    if multiple_objects is not None:
        args['multiple_objects'] = multiple_objects
    if group_objects is not None:
        args['group_objects'] = group_objects
    if repetitions is not None:
        args['repetitions'] = repetitions
    if destination is not None:
        args['destination'] = destination
    args.update(extra)
    return invoke_runtime_tool('transform-shape', args, workspace=workspace, timeout_seconds=timeout_seconds)


def update_status(*, task_path: str, run_id: str, status: str, stage: str, best_result_json: str, output_files_json: str, error_json: str, extra_json: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Update the formal run status.json file."""
    args: dict[str, Any] = {}
    args['task_path'] = task_path
    args['run_id'] = run_id
    args['status'] = status
    args['stage'] = stage
    args['best_result_json'] = best_result_json
    args['output_files_json'] = output_files_json
    args['error_json'] = error_json
    args['extra_json'] = extra_json
    args.update(extra)
    return invoke_runtime_tool('update-status', args, workspace=workspace, timeout_seconds=timeout_seconds)


def verify_project_identity(*, project_path: str, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Verify the expected project is the sole open CST project before writes."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args.update(extra)
    return invoke_runtime_tool('verify-project-identity', args, workspace=workspace, timeout_seconds=timeout_seconds)


def wait_project_unlocked(*, project_path: str, timeout_seconds_: float, poll_interval_seconds: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Wait for a project companion directory to have no .lok files."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['timeout_seconds'] = timeout_seconds_
    args['poll_interval_seconds'] = poll_interval_seconds
    args.update(extra)
    return invoke_runtime_tool('wait-project-unlocked', args, workspace=workspace, timeout_seconds=timeout_seconds)


def wait_simulation(*, project_path: str, timeout_seconds_: float, poll_interval_seconds: float, workspace: str | None = None, timeout_seconds: float | None = None, **extra: Any) -> dict[str, Any]:
    """Poll is-simulation-running until the solver finishes or timeout expires."""
    args: dict[str, Any] = {}
    args['project_path'] = project_path
    args['timeout_seconds'] = timeout_seconds_
    args['poll_interval_seconds'] = poll_interval_seconds
    args.update(extra)
    return invoke_runtime_tool('wait-simulation', args, workspace=workspace, timeout_seconds=timeout_seconds)
