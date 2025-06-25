"""
NetConfig Automation - Configuration Manager (Continued)
Core module for network configuration management and deployment
"""

            self.logger.error(f"Compliance check failed: {e}")
            return {
                'success': False,
                'error': f'Compliance check failed: {str(e)}'
            }
    
    async def rollback_config(self, config_id: str, 
                            devices: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Rollback to a previous configuration
        
        Args:
            config_id: Configuration ID to rollback to
            devices: Specific devices to rollback (optional)
            
        Returns:
            Dict containing rollback results
        """
        self.logger.info(f"Starting configuration rollback: config_id={config_id}")
        
        try:
            # Get configuration from database
            with get_db_session() as session:
                config = session.query(Configuration).filter_by(id=config_id).first()
                if not config:
                    return {
                        'success': False,
                        'error': f'Configuration {config_id} not found'
                    }
            
            # Get target devices
            if devices:
                target_devices = await self._get_target_devices(devices)
            else:
                # Get devices from original deployment
                target_devices = await self._get_devices_from_deployment(config.deployment_id)
            
            if not target_devices:
                return {
                    'success': False,
                    'error': 'No valid devices found'
                }
            
            # Create semaphore for concurrent rollbacks
            semaphore = asyncio.Semaphore(5)
            
            tasks = []
            for device in target_devices:
                task = self._rollback_device_config(semaphore, device, config)
                tasks.append(task)
            
            # Execute rollbacks concurrently
            rollback_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            results = []
            for i, result in enumerate(rollback_results):
                if isinstance(result, Exception):
                    results.append({
                        'device': target_devices[i]['name'],
                        'success': False,
                        'error': str(result),
                        'timestamp': datetime.utcnow().isoformat()
                    })
                else:
                    results.append(result)
            
            successful_rollbacks = sum(1 for r in results if r.get('success'))
            
            return {
                'success': successful_rollbacks > 0,
                'results': results,
                'summary': {
                    'total_devices': len(results),
                    'successful': successful_rollbacks,
                    'failed': len(results) - successful_rollbacks
                }
            }
            
        except Exception as e:
            self.logger.error(f"Configuration rollback failed: {e}")
            return {
                'success': False,
                'error': f'Rollback failed: {str(e)}'
            }
    
    def validate_config(self, template: str, devices: List[str], 
                       variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Validate configuration template without deploying
        
        Args:
            template: Template filename
            devices: List of device names
            variables: Template variables
            
        Returns:
            Dict containing validation results
        """
        try:
            # Load template
            template_content = self._load_template(template)
            if not template_content:
                return {
                    'success': False,
                    'error': f'Template {template} not found'
                }
            
            # Render template with sample variables
            sample_variables = variables or {}
            sample_variables.update({
                'hostname': 'sample-device',
                'management_ip': '192.168.1.1',
                'device_type': 'cisco_ios'
            })
            
            rendered_config = self._render_template(template_content, sample_variables)
            
            # Validate syntax
            validation_result = validate_configuration(rendered_config, 'cisco_ios')
            
            return {
                'success': validation_result.get('valid', False),
                'preview': rendered_config,
                'validation_errors': validation_result.get('errors', []),
                'warnings': validation_result.get('warnings', [])
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Validation failed: {str(e)}'
            }
    
    # Helper methods
    
    def _load_template(self, template_name: str) -> Optional[str]:
        """Load configuration template"""
        try:
            template_file = self.template_dir / template_name
            if template_file.exists():
                return template_file.read_text()
            return None
        except Exception as e:
            self.logger.error(f"Failed to load template {template_name}: {e}")
            return None
    
    def _render_template(self, template_content: str, variables: Dict[str, Any]) -> str:
        """Render Jinja2 template with variables"""
        template = self.jinja_env.from_string(template_content)
        return template.render(**variables)
    
    async def _get_target_devices(self, devices: List[str]) -> List[Dict[str, Any]]:
        """Get target devices for operation"""
        if devices == ['all']:
            return self.device_manager.get_all_devices()
        else:
            target_devices = []
            for device_name in devices:
                device = self.device_manager.get_device_by_name(device_name)
                if device:
                    target_devices.append(device)
                else:
                    self.logger.warning(f"Device {device_name} not found")
            return target_devices
    
    def _get_connection_params(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Get Netmiko connection parameters for device"""
        return {
            'device_type': device['device_type'],
            'host': device['ip_address'],
            'username': device['credentials']['username'],
            'password': device['credentials']['password'],
            'port': device.get('port', 22),
            'timeout': 30,
            'session_timeout': 60,
            'auth_timeout': 30,
            'banner_timeout': 15,
            'conn_timeout': 10
        }
    
    def _generate_deployment_id(self) -> str:
        """Generate unique deployment ID"""
        import uuid
        return str(uuid.uuid4())
    
    async def _create_device_backup(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Create backup before configuration deployment"""
        try:
            backup_result = await self.backup_manager.create_backup(device)
            return backup_result
        except Exception as e:
            self.logger.warning(f"Failed to create backup for {device['name']}: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _store_deployment_history(self, deployment_id: str, template: str,
                                      devices: List[str], variables: Dict[str, Any],
                                      results: List[Dict[str, Any]], success_rate: float):
        """Store deployment history in database"""
        try:
            with get_db_session() as session:
                history = ConfigurationHistory(
                    deployment_id=deployment_id,
                    template=template,
                    devices=json.dumps(devices),
                    variables=json.dumps(variables),
                    results=json.dumps(results),
                    success_rate=success_rate,
                    timestamp=datetime.utcnow()
                )
                session.add(history)
                session.commit()
        except Exception as e:
            self.logger.error(f"Failed to store deployment history: {e}")
    
    async def _store_device_configuration(self, device_id: str, deployment_id: str,
                                        configuration: str, success: bool):
        """Store device configuration in database"""
        try:
            with get_db_session() as session:
                config = Configuration(
                    device_id=device_id,
                    deployment_id=deployment_id,
                    configuration=configuration,
                    config_hash=hashlib.md5(configuration.encode()).hexdigest(),
                    applied=success,
                    timestamp=datetime.utcnow()
                )
                session.add(config)
                session.commit()
        except Exception as e:
            self.logger.error(f"Failed to store device configuration: {e}")
    
    async def _check_device_compliance(self, device: Dict[str, Any],
                                     policies: Dict[str, Any]) -> Dict[str, Any]:
        """Check compliance for a single device"""
        try:
            # Get current configuration
            connection_params = self._get_connection_params(device)
            
            loop = asyncio.get_event_loop()
            config_result = await loop.run_in_executor(
                None, self._get_device_configuration, connection_params
            )
            
            if not config_result.get('success'):
                return {
                    'device': device['name'],
                    'compliant': False,
                    'error': config_result.get('error'),
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            # Check against policies
            compliance_issues = []
            config_lines = config_result['configuration'].split('\n')
            
            for policy_name, policy in policies.items():
                if not self._check_policy_compliance(config_lines, policy):
                    compliance_issues.append({
                        'policy': policy_name,
                        'description': policy.get('description', ''),
                        'severity': policy.get('severity', 'medium')
                    })
            
            # Calculate compliance score
            total_policies = len(policies)
            passed_policies = total_policies - len(compliance_issues)
            score = (passed_policies / total_policies * 100) if total_policies > 0 else 0
            
            return {
                'device': device['name'],
                'compliant': len(compliance_issues) == 0,
                'score': round(score, 1),
                'issues_count': len(compliance_issues),
                'issues': compliance_issues,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Compliance check failed for {device['name']}: {e}")
            return {
                'device': device['name'],
                'compliant': False,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def _get_device_configuration(self, connection_params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current device configuration"""
        try:
            with ConnectHandler(**connection_params) as net_connect:
                configuration = net_connect.send_command("show running-config")
                return {
                    'success': True,
                    'configuration': configuration
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _load_compliance_policies(self) -> Dict[str, Any]:
        """Load compliance policies from configuration"""
        try:
            policies_file = Path("config/compliance_policies.yaml")
            if policies_file.exists():
                with open(policies_file, 'r') as f:
                    return yaml.safe_load(f)
            else:
                # Return default policies
                return {
                    'ssh_enabled': {
                        'description': 'SSH should be enabled',
                        'check_type': 'contains',
                        'pattern': 'ip ssh version 2',
                        'severity': 'high'
                    },
                    'no_telnet': {
                        'description': 'Telnet should be disabled',
                        'check_type': 'not_contains',
                        'pattern': 'transport input telnet',
                        'severity': 'high'
                    },
                    'banner_configured': {
                        'description': 'Login banner should be configured',
                        'check_type': 'contains',
                        'pattern': 'banner login',
                        'severity': 'medium'
                    }
                }
        except Exception as e:
            self.logger.error(f"Failed to load compliance policies: {e}")
            return {}
    
    def _check_policy_compliance(self, config_lines: List[str], policy: Dict[str, Any]) -> bool:
        """Check if configuration complies with a specific policy"""
        check_type = policy.get('check_type', 'contains')
        pattern = policy.get('pattern', '')
        
        config_text = '\n'.join(config_lines)
        
        if check_type == 'contains':
            return pattern in config_text
        elif check_type == 'not_contains':
            return pattern not in config_text
        elif check_type == 'regex':
            import re
            return bool(re.search(pattern, config_text))
        elif check_type == 'line_exists':
            return any(pattern in line for line in config_lines)
        else:
            return True  # Unknown check type, assume compliant
    
    async def _rollback_device_config(self, semaphore, device: Dict[str, Any],
                                    config: 'Configuration') -> Dict[str, Any]:
        """Rollback configuration on a single device"""
        async with semaphore:
            device_name = device['name']
            self.logger.info(f"Rolling back device: {device_name}")
            
            try:
                # Create backup before rollback
                backup_result = await self._create_device_backup(device)
                
                # Get connection parameters
                connection_params = self._get_connection_params(device)
                
                # Execute rollback in thread pool
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._execute_deployment, connection_params, config.configuration
                )
                
                return {
                    'device': device_name,
                    'success': result.get('success', False),
                    'message': result.get('message', ''),
                    'backup_id': backup_result.get('backup_id'),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                self.logger.error(f"Failed to rollback {device_name}: {e}")
                return {
                    'device': device_name,
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.utcnow().isoformat()
                }
    
    async def _get_devices_from_deployment(self, deployment_id: str) -> List[Dict[str, Any]]:
        """Get devices that were part of a specific deployment"""
        try:
            with get_db_session() as session:
                configs = session.query(Configuration).filter_by(deployment_id=deployment_id).all()
                device_ids = [config.device_id for config in configs]
                
                devices = []
                for device_id in device_ids:
                    device = self.device_manager.get_device(device_id)
                    if device:
                        devices.append(device)
                
                return devices
        except Exception as e:
            self.logger.error(f"Failed to get devices from deployment {deployment_id}: {e}")
            return []
