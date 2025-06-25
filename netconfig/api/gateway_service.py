"""
NetConfig Automation - Gateway Service API
REST API for network configuration management
"""

from flask import Flask, request, jsonify
from flask_restful import Api, Resource
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import check_password_hash, generate_password_hash
import asyncio
from datetime import datetime, timedelta
import os

from netconfig.core.config_manager import ConfigManager
from netconfig.core.device_manager import DeviceManager
from netconfig.utils.logger import setup_logger
from netconfig.utils.auth import authenticate_user, create_user
from netconfig.utils.validation import validate_json_schema


def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__)
    
    # Configuration
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'netconfig-secret-key-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
    
    # Initialize extensions
    api = Api(app)
    jwt = JWTManager(app)
    
    # Setup logging
    logger = setup_logger("gateway-api")
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'error': 'Resource not found',
            'message': 'The requested endpoint does not exist'
        }), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        return jsonify({
            'error': 'Internal server error',
            'message': 'An unexpected error occurred'
        }), 500
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'error': 'Bad request',
            'message': 'Invalid request format or parameters'
        }), 400
    
    # Authentication endpoints
    class AuthLogin(Resource):
        def post(self):
            """Authenticate user and return JWT token"""
            try:
                data = request.get_json()
                username = data.get('username')
                password = data.get('password')
                
                if not username or not password:
                    return {'error': 'Username and password required'}, 400
                
                user = authenticate_user(username, password)
                if user:
                    access_token = create_access_token(identity=username)
                    return {
                        'access_token': access_token,
                        'user': {
                            'username': username,
                            'role': user.get('role', 'user')
                        }
                    }, 200
                else:
                    return {'error': 'Invalid credentials'}, 401
                    
            except Exception as e:
                logger.error(f"Authentication error: {e}")
                return {'error': 'Authentication failed'}, 500
    
    # Device management endpoints
    class DeviceList(Resource):
        @jwt_required()
        def get(self):
            """Get list of all managed devices"""
            try:
                device_mgr = DeviceManager()
                devices = device_mgr.get_all_devices()
                
                return {
                    'success': True,
                    'devices': devices,
                    'count': len(devices)
                }, 200
                
            except Exception as e:
                logger.error(f"Error listing devices: {e}")
                return {'error': 'Failed to retrieve devices'}, 500
        
        @jwt_required()
        def post(self):
            """Add a new device"""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['name', 'ip_address', 'device_type', 'credentials']
                for field in required_fields:
                    if field not in data:
                        return {'error': f'Missing required field: {field}'}, 400
                
                device_mgr = DeviceManager()
                result = device_mgr.add_device(data)
                
                if result.get('success'):
                    return {
                        'success': True,
                        'message': 'Device added successfully',
                        'device_id': result.get('device_id')
                    }, 201
                else:
                    return {'error': result.get('error', 'Failed to add device')}, 400
                    
            except Exception as e:
                logger.error(f"Error adding device: {e}")
                return {'error': 'Failed to add device'}, 500
    
    class DeviceDetail(Resource):
        @jwt_required()
        def get(self, device_id):
            """Get specific device details"""
            try:
                device_mgr = DeviceManager()
                device = device_mgr.get_device(device_id)
                
                if device:
                    return {
                        'success': True,
                        'device': device
                    }, 200
                else:
                    return {'error': 'Device not found'}, 404
                    
            except Exception as e:
                logger.error(f"Error retrieving device {device_id}: {e}")
                return {'error': 'Failed to retrieve device'}, 500
        
        @jwt_required()
        def put(self, device_id):
            """Update device configuration"""
            try:
                data = request.get_json()
                device_mgr = DeviceManager()
                result = device_mgr.update_device(device_id, data)
                
                if result.get('success'):
                    return {
                        'success': True,
                        'message': 'Device updated successfully'
                    }, 200
                else:
                    return {'error': result.get('error', 'Failed to update device')}, 400
                    
            except Exception as e:
                logger.error(f"Error updating device {device_id}: {e}")
                return {'error': 'Failed to update device'}, 500
        
        @jwt_required()
        def delete(self, device_id):
            """Delete a device"""
            try:
                device_mgr = DeviceManager()
                result = device_mgr.delete_device(device_id)
                
                if result.get('success'):
                    return {
                        'success': True,
                        'message': 'Device deleted successfully'
                    }, 200
                else:
                    return {'error': result.get('error', 'Failed to delete device')}, 400
                    
            except Exception as e:
                logger.error(f"Error deleting device {device_id}: {e}")
                return {'error': 'Failed to delete device'}, 500
    
    # Configuration deployment endpoints
    class ConfigDeploy(Resource):
        @jwt_required()
        def post(self):
            """Deploy configuration to devices"""
            try:
                data = request.get_json()
                
                # Validate required fields
                required_fields = ['template', 'devices']
                for field in required_fields:
                    if field not in data:
                        return {'error': f'Missing required field: {field}'}, 400
                
                template = data['template']
                devices = data['devices']
                variables = data.get('variables', {})
                dry_run = data.get('dry_run', False)
                
                config_mgr = ConfigManager()
                
                if dry_run:
                    result = config_mgr.validate_config(template, devices, variables)
                else:
                    # Run async operation in sync context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        config_mgr.deploy_config(template, devices, variables)
                    )
                    loop.close()
                
                if result.get('success'):
                    return {
                        'success': True,
                        'message': 'Configuration deployed successfully' if not dry_run else 'Configuration validation successful',
                        'results': result.get('results', []),
                        'deployment_id': result.get('deployment_id')
                    }, 200
                else:
                    return {'error': result.get('error', 'Deployment failed')}, 400
                    
            except Exception as e:
                logger.error(f"Error deploying configuration: {e}")
                return {'error': 'Failed to deploy configuration'}, 500
    
    # Configuration backup endpoints
    class ConfigBackup(Resource):
        @jwt_required()
        def post(self):
            """Backup device configurations"""
            try:
                data = request.get_json() or {}
                devices = data.get('devices', ['all'])
                output_dir = data.get('output_dir', 'backups')
                
                config_mgr = ConfigManager()
                
                # Run async operation in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    config_mgr.backup_configs(devices, output_dir)
                )
                loop.close()
                
                if result.get('success'):
                    return {
                        'success': True,
                        'message': 'Backup completed successfully',
                        'backup_path': result.get('backup_path'),
                        'results': result.get('results', [])
                    }, 200
                else:
                    return {'error': result.get('error', 'Backup failed')}, 400
                    
            except Exception as e:
                logger.error(f"Error backing up configurations: {e}")
                return {'error': 'Failed to backup configurations'}, 500
    
    # Compliance checking endpoints
    class ComplianceCheck(Resource):
        @jwt_required()
        def get(self):
            """Check configuration compliance"""
            try:
                device = request.args.get('device')
                
                config_mgr = ConfigManager()
                
                # Run async operation in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    config_mgr.check_compliance(device)
                )
                loop.close()
                
                if result.get('success'):
                    return {
                        'success': True,
                        'compliance_report': result.get('results', []),
                        'summary': result.get('summary', {}),
                        'timestamp': datetime.utcnow().isoformat()
                    }, 200
                else:
                    return {'error': result.get('error', 'Compliance check failed')}, 400
                    
            except Exception as e:
                logger.error(f"Error checking compliance: {e}")
                return {'error': 'Failed to check compliance'}, 500
    
    # Configuration rollback endpoints
    class ConfigRollback(Resource):
        @jwt_required()
        def post(self):
            """Rollback to previous configuration"""
            try:
                data = request.get_json()
                
                if 'config_id' not in data:
                    return {'error': 'Missing required field: config_id'}, 400
                
                config_id = data['config_id']
                devices = data.get('devices')
                
                config_mgr = ConfigManager()
                
                # Run async operation in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    config_mgr.rollback_config(config_id, devices)
                )
                loop.close()
                
                if result.get('success'):
                    return {
                        'success': True,
                        'message': 'Rollback completed successfully',
                        'results': result.get('results', [])
                    }, 200
                else:
                    return {'error': result.get('error', 'Rollback failed')}, 400
                    
            except Exception as e:
                logger.error(f"Error rolling back configuration: {e}")
                return {'error': 'Failed to rollback configuration'}, 500
    
    # Health check endpoint
    class HealthCheck(Resource):
        def get(self):
            """API health check"""
            return {
                'status': 'healthy',
                'service': 'NetConfig Automation Gateway',
                'version': '1.0.0',
                'timestamp': datetime.utcnow().isoformat()
            }, 200
    
    # API documentation endpoint
    class ApiDocs(Resource):
        def get(self):
            """API documentation"""
            return {
                'service': 'NetConfig Automation Gateway API',
                'version': '1.0.0',
                'endpoints': {
                    'authentication': {
                        'POST /api/v1/auth/login': 'Authenticate and get JWT token'
                    },
                    'devices': {
                        'GET /api/v1/devices': 'List all devices',
                        'POST /api/v1/devices': 'Add new device',
                        'GET /api/v1/devices/<id>': 'Get device details',
                        'PUT /api/v1/devices/<id>': 'Update device',
                        'DELETE /api/v1/devices/<id>': 'Delete device'
                    },
                    'configuration': {
                        'POST /api/v1/deploy': 'Deploy configuration',
                        'POST /api/v1/backup': 'Backup configurations',
                        'POST /api/v1/rollback': 'Rollback configuration'
                    },
                    'compliance': {
                        'GET /api/v1/compliance': 'Check compliance'
                    },
                    'system': {
                        'GET /api/v1/health': 'Health check',
                        'GET /api/v1/docs': 'API documentation'
                    }
                },
                'authentication': {
                    'type': 'JWT Bearer Token',
                    'header': 'Authorization: Bearer <token>'
                }
            }, 200
    
    # Register API endpoints
    api.add_resource(HealthCheck, '/api/v1/health')
    api.add_resource(ApiDocs, '/api/v1/docs')
    api.add_resource(AuthLogin, '/api/v1/auth/login')
    api.add_resource(DeviceList, '/api/v1/devices')
    api.add_resource(DeviceDetail, '/api/v1/devices/<string:device_id>')
    api.add_resource(ConfigDeploy, '/api/v1/deploy')
    api.add_resource(ConfigBackup, '/api/v1/backup')
    api.add_resource(ComplianceCheck, '/api/v1/compliance')
    api.add_resource(ConfigRollback, '/api/v1/rollback')
    
    # Add CORS headers
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        return response
    
    logger.info("NetConfig Automation Gateway API initialized")
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8080, debug=True)
