import sys
import importlib

print(f"Python version: {sys.version.split()[0]}")

libraries = ["numpy", "pandas", "sklearn", "matplotlib"]
display_names = {"sklearn": "scikit-learn"}

for lib in libraries:
    try:
        module = importlib.import_module(lib)
        name = display_names.get(lib, lib)
        print(f"{name} version: {module.__version__}")
    except ImportError:
        name = display_names.get(lib, lib)
        print(f"{name}: NOT INSTALLED — run: pip install {lib}")

try:
    import torch
    print(f"GPU available: {torch.cuda.is_available()}")
except ImportError:
    print("GPU available: False (torch not installed)")