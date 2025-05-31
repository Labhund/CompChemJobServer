from flask import Flask
import json
from pathlib import Path

# Determine the path to config.json relative to this file (app.py)
_current_file_path = Path(__file__).resolve()
_src_dir = _current_file_path.parent
_default_config_file_path = _src_dir / "config.json"

def load_config(config_path=_default_config_file_path): # Use the determined path as default
    """Loads configuration from a JSON file, with defaults."""
    default_config = {
        'job_dir': './comp_jobs_orca', # Default to a local directory
        'orca_path': '/opt/orca/orca', # Default ORCA path
        'max_concurrent_jobs': 2,
        'host': '0.0.0.0',
        'port': 8080
    }
    try:
        # config_path will now be an absolute Path object if default is used
        with open(config_path, 'r') as f:
            user_config = json.load(f)
            default_config.update(user_config)
            print(f"Loaded configuration from {config_path}")
    except FileNotFoundError:
        print(f"Warning: {config_path} not found. Using default configuration.")
    except json.JSONDecodeError:
        print(f"Warning: Error decoding {config_path}. Using default configuration.")
    return default_config

CONFIG = load_config()
app = Flask(__name__)

# Ensure job directory exists (moved here for clarity or can be in manager init)
Path(CONFIG['job_dir']).mkdir(parents=True, exist_ok=True)
Path(CONFIG['job_dir'], 'input').mkdir(exist_ok=True)
Path(CONFIG['job_dir'], 'output').mkdir(exist_ok=True)
Path(CONFIG['job_dir'], 'scratch').mkdir(exist_ok=True)

print("🚀 Initializing ORCA Job Server application...")
print(f"📁 Job directory: {Path(CONFIG['job_dir']).resolve()}")
print(f"🛠️ ORCA path: {CONFIG['orca_path']}")
print(f"⚡ Max concurrent jobs: {CONFIG['max_concurrent_jobs']}")
print(f"🌐 Server will be available at: http://{CONFIG['host']}:{CONFIG['port']}")
if CONFIG['host'] == '0.0.0.0':
    print(f"🔗 Access from other devices on your network using your machine's IP: http://[your-machine-ip]:{CONFIG['port']}")