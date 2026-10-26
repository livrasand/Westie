import pathlib
import sys
import importlib.util

# Add project root to sys.path for relative imports
project_root = pathlib.Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load the FastAPI app defined in git_text_cli.py
git_cli_path = project_root / "git_text_cli.py"
spec = importlib.util.spec_from_file_location("git_text_cli", str(git_cli_path))
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None, "Failed to load git_text_cli module"
spec.loader.exec_module(module)  # type: ignore[arg-type]

app = module.app

# Debug endpoint to list routes and allowed methods
@app.get("/debug/routes")
def debug_routes():
    return {route.path: list(route.methods) for route in app.routes}
