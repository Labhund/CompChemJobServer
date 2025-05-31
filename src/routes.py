from flask import request, jsonify, send_file # Ensure send_file is imported if not already
from pathlib import Path
from datetime import datetime
import uuid # For generating default names if needed

from .app import app, CONFIG 
from .manager import job_manager 

@app.route('/api/submit', methods=['POST'])
def submit_job_route():
  try:
      job_data = request.get_json()
      if not job_data or 'input_content' not in job_data:
          return jsonify({'error': 'Missing input_content in JSON payload'}), 400
      # Ensure program is set to orca if not provided or override
      job_data['program'] = 'orca'
      job_id = job_manager.submit_job(job_data)
      return jsonify({'job_id': job_id, 'status': 'submitted', 'message': f'Job {job_id} submitted successfully.'}), 201
  except Exception as e:
      app.logger.error(f"Error in submit_job_route: {e}", exc_info=True)
      return jsonify({'error': str(e)}), 500

@app.route('/api/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
  if job_id not in job_manager.jobs:
      return jsonify({'error': 'Job not found'}), 404
  job = job_manager.jobs[job_id].copy()
  job.pop('input_content', None)
  return jsonify(job)

@app.route('/api/output/<job_id>/<filename>', methods=['GET'])
def get_output_file(job_id, filename):
  if job_id not in job_manager.jobs:
      return jsonify({'error': 'Job not found'}), 404
  file_path = Path(CONFIG['job_dir'], 'output', job_id, filename)
  if not file_path.exists() or not file_path.is_file():
      return jsonify({'error': f'File {filename} not found for job {job_id}'}), 404
  return send_file(str(file_path), as_attachment=True)

@app.route('/api/jobs', methods=['GET'])
def list_jobs_route():
  job_list = []
  sorted_jobs = sorted(job_manager.jobs.values(), key=lambda j: j['submitted_at'], reverse=True)
  for job_details in sorted_jobs: # Renamed 'job' to 'job_details' to avoid conflict
      job_summary = {
          'id': job_details['id'],
          'name': job_details['name'],
          'program': job_details['program'],
          'status': job_details['status'],
          'submitted_at': job_details['submitted_at'],
          'started_at': job_details.get('started_at'),
          'completed_at': job_details.get('completed_at')
      }
      job_list.append(job_summary)
  return jsonify(job_list)

@app.route('/api/health', methods=['GET'])
def health_check():
  with job_manager.lock:
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
  with job_manager.lock:
    running = job_manager.running_jobs
    queued = len(job_manager.job_queue)
    total = len(job_manager.jobs)
  
  return f"""
  <html>
  <head><title>ORCA Job Server</title>
  <style> body {{ font-family: sans-serif; margin: 20px; }} h1, h2 {{ color: #333; }} ul {{ list-style-type: none; padding: 0; }} li {{ margin-bottom: 5px; }} code {{ background-color: #f4f4f4; padding: 2px 4px; border-radius: 3px; }} </style>
  </head>
  <body>
      <h1>🧪 ORCA Job Server</h1>
      <h2>Server Status</h2>
      <ul>
          <li>Running Jobs: {running} / {CONFIG['max_concurrent_jobs']}</li>
          <li>Queued Jobs: {queued}</li>
          <li>Total Jobs Processed: {total}</li>
      </ul>
      <h2>API Endpoints</h2>
      <ul>
          <li><code>POST /api/submit</code> - Submit job (JSON: {{"name": "my_orca_job", "input_content": "..."}})</li>
          <li><code>GET /api/status/&lt;job_id&gt;</code> - Get job status</li>
          <li><code>GET /api/output/&lt;job_id&gt;/&lt;filename&gt;</code> - Download output file</li>
          <li><code>GET /api/jobs</code> - List all jobs</li>
          <li><code>GET /api/health</code> - Health check</li>
      </ul>
      <p><small>Server time: {datetime.now().isoformat()}</small></p>
  </body>
  </html>
  """

# --- New routes for IQMol compatibility ---

@app.route('/submit', methods=['POST'])
def iqmol_submit_job():
    """
    Handles job submission from IQMol.
    IQMol sends input content as raw request body.
    IQMol expects 'jobid' and 'cookie' in the JSON response.
    """
    # iqmol_cookie = request.args.get('cookie') # IQMol sends this, use if needed
    input_content = request.get_data(as_text=True)

    if not input_content:
        return jsonify({'error': 'Missing input_content in request body'}), 400

    job_data_for_manager = {
        'input_content': input_content,
        'name': f"iqmol_job_{str(uuid.uuid4())[:8]}" 
        # 'program' is hardcoded to 'orca' in your job_manager.submit_job
    }
    try:
        job_id = job_manager.submit_job(job_data_for_manager)
        # IQMol expects 'jobid'. It also sends a 'cookie' which we can echo back.
        return jsonify({'jobid': job_id, 'cookie': request.args.get('cookie', '')}), 201
    except Exception as e:
        app.logger.error(f"Error in iqmol_submit_job: {e}", exc_info=True)
        return jsonify({'error': str(e), 'status': 'error_submitting'}), 500 # IQMol might expect a status field

@app.route('/status', methods=['GET'])
def iqmol_get_job_status():
    """
    Handles job status requests from IQMol.
    IQMol sends 'jobid' as a query parameter.
    IQMol expects a 'status' field in the JSON response.
    """
    job_id = request.args.get('jobid')
    # iqmol_cookie = request.args.get('cookie') # Use if needed

    if not job_id:
        return jsonify({'error': 'Missing jobid parameter', 'status': 'error_bad_request'}), 400

    if job_id not in job_manager.jobs:
        return jsonify({'status': 'unknown'}), 404 # Or 200 with status 'unknown' as per Claude's example

    job_details = job_manager.jobs[job_id]
    # IQMol's example response is just {'status': '...'}
    # You can add more details if IQMol can handle them, or stick to the minimal requirement.
    response_data = {'status': job_details['status']}
    # Optionally, add more fields if IQMol can use them:
    # response_data['jobid'] = job_id
    # response_data['name'] = job_details.get('name')
    # response_data['submitted_at'] = job_details.get('submitted_at')
    # response_data['completed_at'] = job_details.get('completed_at')
    # response_data['error'] = job_details.get('error')
    return jsonify(response_data)

@app.route('/list', methods=['GET'])
def iqmol_list_files():
    """
    Handles requests to list output files for a job from IQMol.
    IQMol sends 'jobid' as a query parameter.
    IQMol expects a 'files' field (a list of filenames) in the JSON response.
    """
    job_id = request.args.get('jobid')
    # iqmol_cookie = request.args.get('cookie') # Use if needed

    if not job_id:
        return jsonify({'error': 'Missing jobid parameter', 'files': []}), 400

    if job_id not in job_manager.jobs:
        return jsonify({'error': 'Job not found', 'files': []}), 404
    
    job_details = job_manager.jobs[job_id]
    # Your job_manager.collect_output_files populates 'output_files'
    output_files = job_details.get('output_files', [])
    
    # IQMol might expect just filenames, not full paths.
    # Your current 'output_files' stores just filenames relative to the job's output dir.
    return jsonify({'files': output_files})

@app.route('/download', methods=['GET'])
def iqmol_download_file():
    """
    Handles file download requests from IQMol.
    IQMol sends 'jobid' and 'file' (filename) as query parameters.
    """
    job_id = request.args.get('jobid')
    filename = request.args.get('file')
    # iqmol_cookie = request.args.get('cookie') # Use if needed

    if not job_id or not filename:
        return jsonify({'error': 'Missing jobid or file parameter'}), 400

    if job_id not in job_manager.jobs:
        return jsonify({'error': 'Job not found'}), 404

    # Construct the file path similar to your existing /api/output route
    # Output files are in CONFIG['job_dir'] / 'output' / job_id / filename
    file_path = Path(CONFIG['job_dir'], 'output', job_id, filename)

    if not file_path.exists() or not file_path.is_file():
        return jsonify({'error': f'File {filename} not found for job {job_id}'}), 404
    
    return send_file(str(file_path), as_attachment=True)

@app.route('/delete', methods=['GET']) # Or POST, depending on IQMol's actual call
def iqmol_delete_job():
    """
    Handles job deletion/cancellation requests from IQMol.
    IQMol sends 'jobid' as a query parameter.
    This endpoint needs corresponding logic in your JobManager.
    """
    job_id = request.args.get('jobid')
    # iqmol_cookie = request.args.get('cookie') # Use if needed

    if not job_id:
        return jsonify({'error': 'Missing jobid parameter', 'status': 'error_bad_request'}), 400

    # --- Placeholder for actual deletion logic ---
    # You'll need to implement job cancellation/deletion in your JobManager.
    # This might involve:
    # 1. Removing from queue if queued.
    # 2. Terminating the process if running.
    # 3. Cleaning up files.
    # 4. Removing from self.jobs dictionary.
    
    if job_id in job_manager.jobs:
        # Example: job_manager.cancel_job(job_id) # You'd need to create this method
        # For now, let's assume it's removed from the dictionary if found
        # This is a simplified placeholder:
        with job_manager.lock:
            if job_id in job_manager.jobs:
                # Basic removal, real cancellation is more complex for running jobs
                job_manager.jobs.pop(job_id, None) 
                # If it was in the queue, remove it
                if job_id in job_manager.job_queue:
                    job_manager.job_queue.remove(job_id)
                # If it was running, this simple pop won't stop the thread/process.
                # Proper cancellation of a running subprocess is non-trivial.
        app.logger.info(f"IQMol requested delete for job {job_id}. Placeholder removal executed.")
        return jsonify({'status': 'deleted'}) # Or 'cancelled'
    else:
        return jsonify({'status': 'not_found'}), 404
    # --- End placeholder ---

# Ensure this file (routes.py) is imported in your __init__.py or app.py
# so these routes are registered with the Flask app instance.
# Your src/__init__.py already imports .routes, which is good.