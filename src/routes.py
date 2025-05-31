from flask import request, jsonify, send_file
from pathlib import Path
from datetime import datetime

from .app import app, CONFIG # Import app and CONFIG from app.py
from .manager import job_manager # Import job_manager from manager.py

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