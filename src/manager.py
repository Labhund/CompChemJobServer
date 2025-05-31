import subprocess
import threading
import uuid
import json
from datetime import datetime
from pathlib import Path
import shutil
from .app import CONFIG # Import CONFIG from app.py

class JobManager:
  def __init__(self):
      self.jobs = {}
      self.job_queue = []
      self.running_jobs = 0
      self.lock = threading.Lock()
      # self.ensure_job_directory() # Can be called from app.py or here

  # def ensure_job_directory(self): # Definition as in your job_server.py
      # ...

  def submit_job(self, job_data):
      job_id = str(uuid.uuid4())
      job = {
          'id': job_id,
          'name': job_data.get('name', f'job_{job_id[:8]}'),
          'program': 'orca', # Hardcode to orca or ensure it's always orca
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
      with self.lock:
          if self.running_jobs >= CONFIG['max_concurrent_jobs'] or not self.job_queue:
              return
          job_id = self.job_queue.pop(0)
          self.running_jobs += 1
      thread = threading.Thread(target=self.run_job, args=(job_id,))
      thread.daemon = True
      thread.start()

  def run_job(self, job_id):
      job = self.jobs[job_id]
      try:
          job['status'] = 'running'
          job['started_at'] = datetime.now().isoformat()
          
          input_file = Path(CONFIG['job_dir'], 'input', f"{job_id}.inp")
          output_dir_base = Path(CONFIG['job_dir'], 'output')
          output_file = output_dir_base / f"{job_id}.out"
          scratch_dir_base = Path(CONFIG['job_dir'], 'scratch')
          scratch_dir = scratch_dir_base / job_id
          scratch_dir.mkdir(exist_ok=True)
          
          # Simplified for ORCA only
          orca_input_in_scratch = scratch_dir / f"{job_id}.inp"
          shutil.copy(input_file, orca_input_in_scratch)
          cmd = [CONFIG['orca_path'], str(orca_input_in_scratch)]
          run_cwd = scratch_dir
          
          print(f"Running ORCA job {job_id}: {' '.join(cmd)} in {run_cwd}")
          
          result = subprocess.run(
              cmd,
              cwd=str(run_cwd),
              capture_output=True,
              text=True,
              timeout=3600  # 1 hour timeout
          )
          
          if result.stdout: # ORCA writes main output to stdout
              with open(output_file, 'w') as f_out:
                  f_out.write(result.stdout)
          if result.stderr:
              with open(output_dir_base / f"{job_id}.err", 'w') as f_err:
                  f_err.write(result.stderr)

          if result.returncode == 0:
              job['status'] = 'completed'
              self.collect_output_files(job_id, scratch_dir)
          else:
              job['status'] = 'failed'
              error_message = f"Return code: {result.returncode}\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}"
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
          # shutil.rmtree(scratch_dir, ignore_errors=True) # Optional cleanup
          self.process_queue()

  def collect_output_files(self, job_id, scratch_dir):
      output_job_dir = Path(CONFIG['job_dir'], 'output', job_id)
      output_job_dir.mkdir(parents=True, exist_ok=True)
      job = self.jobs[job_id]
      job['output_files'] = []

      main_output_file_src = Path(CONFIG['job_dir'], 'output', f"{job_id}.out")
      if main_output_file_src.exists():
          shutil.move(str(main_output_file_src), str(output_job_dir / f"{job_id}.out"))
          job['output_files'].append(f"{job_id}.out")

      extensions_to_collect = ['.log', '.xyz', '.molden', '.gbw', '.prop', '.hess', '.opt', '.cis'] # Common ORCA extensions
      for file_path in Path(scratch_dir).glob('*'):
          if file_path.is_file():
              if file_path.name == f"{job_id}.inp": # Don't copy input back
                  continue
              if any(file_path.name.endswith(ext) for ext in extensions_to_collect) or '.gbw' in file_path.name or '.scfp' in file_path.name: # More flexible collection
                  dest_file = output_job_dir / file_path.name
                  try:
                      shutil.copy(file_path, dest_file)
                      job['output_files'].append(file_path.name)
                  except Exception as e:
                      print(f"Error copying {file_path} to {dest_file}: {e}")
      
      orca_err_file_src = Path(CONFIG['job_dir'], 'output', f"{job_id}.err")
      if orca_err_file_src.exists():
          shutil.move(str(orca_err_file_src), str(output_job_dir / f"{job_id}.err"))
          job['output_files'].append(f"{job_id}.err")

job_manager = JobManager()