#!/usr/bin/env python3
"""
Computational Chemistry Job Server for IQmol
Supports Q-Chem and ORCA calculations via HTTP API
"""

from flask import Flask, request, jsonify, send_file
import os
import subprocess
import threading
import time
import uuid
import json
from datetime import datetime
from pathlib import Path
import shutil

app = Flask(__name__)

# Configuration
def load_config(config_path="config.json"):
    """Loads configuration from a JSON file, with defaults."""
    default_config = {
        'job_dir': './comp_jobs', # Default to a local directory
        'qchem_path': '/opt/qchem/bin/qchem',
        'orca_path': '/opt/orca/orca',
        'max_concurrent_jobs': 2,
        'host': '0.0.0.0',
        'port': 8080
    }
    try:
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

class JobManager:
  def __init__(self):
      self.jobs = {}
      self.job_queue = []
      self.running_jobs = 0
      self.lock = threading.Lock() # For thread-safe access to shared resources
      self.ensure_job_directory()
  
  def ensure_job_directory(self):
      """Create job directory structure"""
      Path(CONFIG['job_dir']).mkdir(parents=True, exist_ok=True)
      Path(CONFIG['job_dir'], 'input').mkdir(exist_ok=True)
      Path(CONFIG['job_dir'], 'output').mkdir(exist_ok=True)
      Path(CONFIG['job_dir'], 'scratch').mkdir(exist_ok=True)
  
  def submit_job(self, job_data):
      """Submit a new computational job"""
      job_id = str(uuid.uuid4())
      
      job = {
          'id': job_id,
          'name': job_data.get('name', f'job_{job_id[:8]}'),
          'program': job_data.get('program', 'qchem').lower(),
          'input_content': job_data.get('input_content', ''),
          'status': 'queued',
          'submitted_at': datetime.now().isoformat(),
          'started_at': None,
          'completed_at': None,
          'error': None,
          'output_files': []
      }
      
      input_file_dir = Path(CONFIG['job_dir'], 'input')
      input_file = input_file_dir / f"{job_id}.inp"
      with open(input_file, 'w') as f:
          f.write(job['input_content'])
      
      with self.lock:
          self.jobs[job_id] = job
          self.job_queue.append(job_id)
      
      self.process_queue()
      
      return job_id
  
  def process_queue(self):
      """Process jobs in the queue"""
      with self.lock:
          if self.running_jobs >= CONFIG['max_concurrent_jobs']:
              return
          
          if not self.job_queue:
              return
          
          job_id = self.job_queue.pop(0)
          self.running_jobs += 1
          
      # Start job in background thread
      thread = threading.Thread(target=self.run_job, args=(job_id,))
      thread.daemon = True # Ensures thread exits when main program exits
      thread.start()
  
  def run_job(self, job_id):
      """Execute a computational job"""
      job = self.jobs[job_id] # Get job from instance storage
      
      try:
          job['status'] = 'running'
          job['started_at'] = datetime.now().isoformat()
          
          input_file = Path(CONFIG['job_dir'], 'input', f"{job_id}.inp")
          output_dir_base = Path(CONFIG['job_dir'], 'output')
          output_file = output_dir_base / f"{job_id}.out" # Main output file
          scratch_dir_base = Path(CONFIG['job_dir'], 'scratch')
          scratch_dir = scratch_dir_base / job_id
          
          scratch_dir.mkdir(exist_ok=True)
          
          cmd = []
          run_cwd = scratch_dir

          if job['program'] == 'qchem':
              # Q-Chem typically writes its main output to the second argument
              # and uses the third argument as a scratch directory name prefix.
              # For simplicity, we'll let Q-Chem write its output file directly.
              # The output_file path here is more for our reference.
              cmd = [CONFIG['qchem_path'], str(input_file), str(output_file), job_id] # Pass job_id as scratch prefix
              # Q-Chem often prefers to run where the input file is, or specify full paths.
              # Running in scratch_dir is common.
          elif job['program'] == 'orca':
              orca_input_in_scratch = scratch_dir / f"{job_id}.inp"
              shutil.copy(input_file, orca_input_in_scratch)
              cmd = [CONFIG['orca_path'], str(orca_input_in_scratch)]
              # ORCA typically writes output files in the directory it's run from.
          else:
              raise ValueError(f"Unsupported program: {job['program']}")
          
          print(f"Running job {job_id} ({job['program']}): {' '.join(cmd)} in {run_cwd}")
          
          result = subprocess.run(
              cmd,
              cwd=str(run_cwd),
              capture_output=True,
              text=True,
              timeout=3600  # 1 hour timeout
          )
          
          # For ORCA, the main output is stdout, which we can save.
          # For Q-Chem, it writes to output_file directly.
          if job['program'] == 'orca' and result.stdout:
              with open(output_file, 'w') as f_out:
                  f_out.write(result.stdout)
              if result.stderr: # ORCA might also print to stderr
                 with open(output_dir_base / f"{job_id}.err", 'w') as f_err:
                    f_err.write(result.stderr)


          if result.returncode == 0:
              job['status'] = 'completed'
              self.collect_output_files(job_id, scratch_dir)
          else:
              job['status'] = 'failed'
              error_message = f"Return code: {result.returncode}\n"
              error_message += f"Stdout:\n{result.stdout}\n"
              error_message += f"Stderr:\n{result.stderr}"
              job['error'] = error_message
              print(f"Job {job_id} failed. Error: {error_message}")
          
          job['completed_at'] = datetime.now().isoformat()
          
      except subprocess.TimeoutExpired:
          job['status'] = 'failed'
          job['error'] = 'Job execution timed out.'
          job['completed_at'] = datetime.now().isoformat()
          print(f"Job {job_id} timed out.")
      except Exception as e:
          job['status'] = 'failed'
          job['error'] = str(e)
          job['completed_at'] = datetime.now().isoformat()
          print(f"Job {job_id} encountered an exception: {e}")
      
      finally:
          with self.lock:
              self.running_jobs -= 1
          # Clean up scratch directory (optional, can be large)
          # shutil.rmtree(scratch_dir, ignore_errors=True)
          self.process_queue()
  
  def collect_output_files(self, job_id, scratch_dir):
      """Collect output files from scratch directory to the main job output directory."""
      output_job_dir = Path(CONFIG['job_dir'], 'output', job_id)
      output_job_dir.mkdir(parents=True, exist_ok=True) # Create a dedicated subdir for this job's outputs
      
      job = self.jobs[job_id]
      job['output_files'] = [] # Reset list

      # The main .out file (Q-Chem writes it directly, ORCA's stdout was saved to it)
      main_output_file_src = Path(CONFIG['job_dir'], 'output', f"{job_id}.out")
      main_output_file_dest = output_job_dir / f"{job_id}.out"
      if main_output_file_src.exists():
          shutil.move(str(main_output_file_src), str(main_output_file_dest)) # Move to job-specific output dir
          job['output_files'].append(f"{job_id}.out") # Store relative to job-specific output dir

      # Collect other files from scratch
      extensions_to_collect = ['.log', '.xyz', '.molden', '.gbw', '.fchk', '.wfn', '.cube', '.prop'] # Add more as needed
      
      for file_path in Path(scratch_dir).glob('*'):
          if file_path.is_file():
              # Check if it's the main input to avoid copying it again if it was in scratch
              if file_path.name == f"{job_id}.inp" and job['program'] == 'orca':
                  continue
              if any(file_path.name.endswith(ext) for ext in extensions_to_collect):
                  dest_file = output_job_dir / file_path.name
                  try:
                      shutil.copy(file_path, dest_file)
                      job['output_files'].append(file_path.name) # Store relative name
                  except Exception as e:
                      print(f"Error copying {file_path} to {dest_file}: {e}")
      
      # Also check for the .err file for ORCA
      orca_err_file_src = Path(CONFIG['job_dir'], 'output', f"{job_id}.err")
      if orca_err_file_src.exists():
          orca_err_file_dest = output_job_dir / f"{job_id}.err"
          shutil.move(str(orca_err_file_src), str(orca_err_file_dest))
          job['output_files'].append(f"{job_id}.err")


# Initialize job manager
job_manager = JobManager()

@app.route('/api/submit', methods=['POST'])
def submit_job_route(): # Renamed to avoid conflict with module-level submit_job
  """Submit a new computational job"""
  try:
      job_data = request.get_json()
      if not job_data or 'input_content' not in job_data:
          return jsonify({'error': 'Missing input_content in JSON payload'}), 400
      job_id = job_manager.submit_job(job_data)
      return jsonify({'job_id': job_id, 'status': 'submitted', 'message': f'Job {job_id} submitted successfully.'}), 201
  except Exception as e:
      return jsonify({'error': str(e)}), 400

@app.route('/api/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
  """Get job status"""
  if job_id not in job_manager.jobs:
      return jsonify({'error': 'Job not found'}), 404
  
  job = job_manager.jobs[job_id].copy()
  job.pop('input_content', None) # Don't send full input
  return jsonify(job)

@app.route('/api/output/<job_id>/<filename>', methods=['GET'])
def get_output_file(job_id, filename):
  """Download an output file for a given job."""
  if job_id not in job_manager.jobs:
      return jsonify({'error': 'Job not found'}), 404
  
  # Output files are now in a subdirectory named after the job_id
  file_path = Path(CONFIG['job_dir'], 'output', job_id, filename)
  
  if not file_path.exists() or not file_path.is_file():
      return jsonify({'error': f'File {filename} not found for job {job_id}'}), 404
  
  return send_file(str(file_path), as_attachment=True)

@app.route('/api/jobs', methods=['GET'])
def list_jobs_route(): # Renamed
  """List all jobs"""
  job_list = []
  # Sort jobs by submission time, newest first
  sorted_jobs = sorted(job_manager.jobs.values(), key=lambda j: j['submitted_at'], reverse=True)

  for job in sorted_jobs:
      job_summary = {
          'id': job['id'],
          'name': job['name'],
          'program': job['program'],
          'status': job['status'],
          'submitted_at': job['submitted_at'],
          'started_at': job.get('started_at'),
          'completed_at': job.get('completed_at')
      }
      job_list.append(job_summary)
  
  return jsonify(job_list)

@app.route('/api/health', methods=['GET'])
def health_check():
  """Health check endpoint"""
  with job_manager.lock: # Ensure thread-safe access
    status = {
        'status': 'healthy',
        'running_jobs': job_manager.running_jobs,
        'queued_jobs': len(job_manager.job_queue),
        'total_jobs': len(job_manager.jobs),
        'max_concurrent_jobs': CONFIG['max_concurrent_jobs']
    }
  return jsonify(status)

@app.route('/', methods=['GET'])
def dashboard():
  """Simple dashboard"""
  # This will become more dynamic if you enhance it with JavaScript later
  with job_manager.lock:
    running = job_manager.running_jobs
    queued = len(job_manager.job_queue)
    total = len(job_manager.jobs)
  
  return f"""
  <html>
  <head>
      <title>Computational Chemistry Job Server</title>
      <style> body {{ font-family: sans-serif; margin: 20px; }} h1, h2 {{ color: #333; }} ul {{ list-style-type: none; padding: 0; }} li {{ margin-bottom: 5px; }} code {{ background-color: #f4f4f4; padding: 2px 4px; border-radius: 3px; }} </style>
  </head>
  <body>
      <h1>🧪 Computational Chemistry Job Server</h1>
      <h2>Server Status</h2>
      <ul>
          <li>Running Jobs: {running} / {CONFIG['max_concurrent_jobs']}</li>
          <li>Queued Jobs: {queued}</li>
          <li>Total Jobs Processed: {total}</li>
      </ul>
      <h2>API Endpoints</h2>
      <ul>
          <li><code>POST /api/submit</code> - Submit job (JSON: {{"name": "my_job", "program": "qchem/orca", "input_content": "..."}})</li>
          <li><code>GET /api/status/&lt;job_id&gt;</code> - Get job status</li>
          <li><code>GET /api/output/&lt;job_id&gt;/&lt;filename&gt;</code> - Download output file</li>
          <li><code>GET /api/jobs</code> - List all jobs</li>
          <li><code>GET /api/health</code> - Health check</li>
      </ul>
      <p><small>Server time: {datetime.now().isoformat()}</small></p>
  </body>
  </html>
  """

if __name__ == '__main__':
  print("🚀 Starting Computational Chemistry Job Server...")
  print(f"📁 Job directory: {Path(CONFIG['job_dir']).resolve()}")
  print(f"🛠️ Q-Chem path: {CONFIG['qchem_path']}")
  print(f"🛠️ ORCA path: {CONFIG['orca_path']}")
  print(f"⚡ Max concurrent jobs: {CONFIG['max_concurrent_jobs']}")
  print(f"🌐 Server will be available at: http://{CONFIG['host']}:{CONFIG['port']}")
  if CONFIG['host'] == '0.0.0.0':
      print(f"🔗 Access from other devices on your network (e.g., via Tailscale) using your machine's IP: http://[your-machine-ip]:{CONFIG['port']}")
  
  # Make sure job directory exists before starting
  job_manager.ensure_job_directory()

  app.run(
      host=CONFIG['host'],
      port=CONFIG['port'],
      debug=True # Set to False in production
  )