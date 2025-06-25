#!/usr/bin/env python3
"""
NetConfig Automation - Network Configuration Management Platform
Main application entry point and CLI interface
"""

import click
import asyncio
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from netconfig.core.config_manager import ConfigManager
from netconfig.core.device_manager import DeviceManager
from netconfig.api.gateway_service import create_app
from netconfig.utils.logger import setup_logger
from netconfig.utils.database import init_database

console = Console()
logger = setup_logger("netconfig-cli")


@click.group()
@click.version_option(version="1.0.0", prog_name="NetConfig Automation")
def cli():
    """NetConfig Automation - Enterprise Network Configuration Management"""
    pass


@cli.command()
@click.option('--host', default='0.0.0.0', help='Host to bind the server to')
@click.option('--port', default=8080, help='Port to bind the server to')
@click.option('--debug', is_flag=True, help='Enable debug mode')
def run_server(host, port, debug):
    """Start the NetConfig API gateway service"""
    console.print("🚀 Starting NetConfig Automation Gateway Service...", style="bold green")
    
    app = create_app()
    
    console.print(f"📡 Server running on http://{host}:{port}", style="bold blue")
    console.print("📚 API Documentation: http://localhost:8080/api/docs", style="bold cyan")
    
    try:
        app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        console.print("\n🛑 Server stopped by user", style="bold red")


@cli.command()
def init_db():
    """Initialize the database"""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Initializing database...", total=None)
        
        try:
            init_database()
            console.print("✅ Database initialized successfully!", style="bold green")
        except Exception as e:
            console.print(f"❌ Database initialization failed: {e}", style="bold red")
            sys.exit(1)


@cli.command()
@click.option('--template', required=True, help='Configuration template to deploy')
@click.option('--devices', required=True, help='Comma-separated list of devices or "all"')
@click.option('--variables', help='JSON string of template variables')
@click.option('--dry-run', is_flag=True, help='Show what would be deployed without applying')
def deploy(template, devices, variables, dry_run):
    """Deploy configuration to network devices"""
    console.print(f"🚀 Deploying configuration template: {template}", style="bold green")
    
    # Parse devices
    device_list = devices.split(',') if devices != 'all' else ['all']
    
    # Parse variables
    import json
    vars_dict = {}
    if variables:
        try:
            vars_dict = json.loads(variables)
        except json.JSONDecodeError:
            console.print("❌ Invalid JSON format for variables", style="bold red")
            sys.exit(1)
    
    # Initialize config manager
    config_mgr = ConfigManager()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Deploying configuration...", total=None)
        
        try:
            if dry_run:
                progress.update(task, description="Validating configuration (dry-run)...")
                result = config_mgr.validate_config(template, device_list, vars_dict)
                console.print("✅ Configuration validation successful!", style="bold green")
                console.print("📋 Preview:", style="bold cyan")
                console.print(result.get('preview', 'No preview available'))
            else:
                progress.update(task, description="Deploying to devices...")
                result = asyncio.run(config_mgr.deploy_config(template, device_list, vars_dict))
                
                if result.get('success'):
                    console.print("✅ Configuration deployed successfully!", style="bold green")
                    
                    # Display results table
                    table = Table(title="Deployment Results")
                    table.add_column("Device", style="cyan")
                    table.add_column("Status", style="green")
                    table.add_column("Message")
                    
                    for device_result in result.get('results', []):
                        status_style = "green" if device_result['success'] else "red"
                        table.add_row(
                            device_result['device'],
                            "✅ Success" if device_result['success'] else "❌ Failed",
                            device_result.get('message', ''),
                            style=status_style
                        )
                    
                    console.print(table)
                else:
                    console.print(f"❌ Deployment failed: {result.get('error')}", style="bold red")
                    sys.exit(1)
                    
        except Exception as e:
            console.print(f"❌ Deployment error: {e}", style="bold red")
            sys.exit(1)


@cli.command()
@click.option('--devices', default='all', help='Comma-separated list of devices or "all"')
@click.option('--output-dir', default='backups', help='Directory to store backups')
def backup(devices, output_dir):
    """Backup device configurations"""
    console.print("💾 Starting configuration backup...", style="bold blue")
    
    device_list = devices.split(',') if devices != 'all' else ['all']
    
    config_mgr = ConfigManager()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Backing up configurations...", total=None)
        
        try:
            result = asyncio.run(config_mgr.backup_configs(device_list, output_dir))
            
            if result.get('success'):
                console.print("✅ Backup completed successfully!", style="bold green")
                console.print(f"📁 Backups saved to: {result.get('backup_path')}", style="bold cyan")
                
                # Display backup summary
                table = Table(title="Backup Summary")
                table.add_column("Device", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("File Size")
                
                for backup_result in result.get('results', []):
                    status_style = "green" if backup_result['success'] else "red"
                    table.add_row(
                        backup_result['device'],
                        "✅ Success" if backup_result['success'] else "❌ Failed",
                        backup_result.get('file_size', 'N/A'),
                        style=status_style
                    )
                
                console.print(table)
            else:
                console.print(f"❌ Backup failed: {result.get('error')}", style="bold red")
                sys.exit(1)
                
        except Exception as e:
            console.print(f"❌ Backup error: {e}", style="bold red")
            sys.exit(1)


@cli.command()
@click.option('--format', 'output_format', default='table', 
              type=click.Choice(['table', 'json', 'yaml']), help='Output format')
def list_devices(output_format):
    """List all managed devices"""
    device_mgr = DeviceManager()
    
    try:
        devices = device_mgr.get_all_devices()
        
        if output_format == 'table':
            table = Table(title="Managed Network Devices")
            table.add_column("Name", style="cyan")
            table.add_column("IP Address", style="green")
            table.add_column("Type", style="yellow")
            table.add_column("Status", style="magenta")
            table.add_column("Last Seen")
            
            for device in devices:
                status_style = "green" if device['status'] == 'online' else "red"
                table.add_row(
                    device['name'],
                    device['ip_address'],
                    device['device_type'],
                    device['status'],
                    device.get('last_seen', 'Never'),
                    style=status_style if device['status'] != 'online' else None
                )
            
            console.print(table)
            
        elif output_format == 'json':
            import json
            console.print(json.dumps(devices, indent=2))
            
        elif output_format == 'yaml':
            import yaml
            console.print(yaml.dump(devices, default_flow_style=False))
            
    except Exception as e:
        console.print(f"❌ Error listing devices: {e}", style="bold red")
        sys.exit(1)


@cli.command()
@click.option('--device', help='Specific device to check (optional)')
def compliance_check(device):
    """Check configuration compliance"""
    console.print("🔍 Running compliance check...", style="bold blue")
    
    config_mgr = ConfigManager()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Checking compliance...", total=None)
        
        try:
            result = asyncio.run(config_mgr.check_compliance(device))
            
            if result.get('success'):
                console.print("✅ Compliance check completed!", style="bold green")
                
                # Display compliance summary
                table = Table(title="Compliance Report")
                table.add_column("Device", style="cyan")
                table.add_column("Compliant", style="green")
                table.add_column("Issues Found")
                table.add_column("Score")
                
                for compliance_result in result.get('results', []):
                    compliant = compliance_result.get('compliant', False)
                    status_style = "green" if compliant else "red"
                    
                    table.add_row(
                        compliance_result['device'],
                        "✅ Yes" if compliant else "❌ No",
                        str(compliance_result.get('issues_count', 0)),
                        f"{compliance_result.get('score', 0)}%",
                        style=status_style
                    )
                
                console.print(table)
                
                # Show overall summary
                total_devices = len(result.get('results', []))
                compliant_devices = sum(1 for r in result.get('results', []) if r.get('compliant'))
                console.print(f"\n📊 Overall Compliance: {compliant_devices}/{total_devices} devices ({(compliant_devices/total_devices*100):.1f}%)", 
                            style="bold cyan")
            else:
                console.print(f"❌ Compliance check failed: {result.get('error')}", style="bold red")
                sys.exit(1)
                
        except Exception as e:
            console.print(f"❌ Compliance check error: {e}", style="bold red")
            sys.exit(1)


@cli.command()
@click.argument('config_id')
@click.option('--devices', help='Comma-separated list of devices to rollback')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
def rollback(config_id, devices, confirm):
    """Rollback to a previous configuration"""
    if not confirm:
        if not click.confirm(f"Are you sure you want to rollback to configuration {config_id}?"):
            console.print("🚫 Rollback cancelled", style="bold yellow")
            return
    
    console.print(f"⏪ Rolling back to configuration: {config_id}", style="bold yellow")
    
    device_list = devices.split(',') if devices else None
    config_mgr = ConfigManager()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Rolling back configuration...", total=None)
        
        try:
            result = asyncio.run(config_mgr.rollback_config(config_id, device_list))
            
            if result.get('success'):
                console.print("✅ Rollback completed successfully!", style="bold green")
                
                # Display rollback results
                table = Table(title="Rollback Results")
                table.add_column("Device", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Message")
                
                for rollback_result in result.get('results', []):
                    status_style = "green" if rollback_result['success'] else "red"
                    table.add_row(
                        rollback_result['device'],
                        "✅ Success" if rollback_result['success'] else "❌ Failed",
                        rollback_result.get('message', ''),
                        style=status_style
                    )
                
                console.print(table)
            else:
                console.print(f"❌ Rollback failed: {result.get('error')}", style="bold red")
                sys.exit(1)
                
        except Exception as e:
            console.print(f"❌ Rollback error: {e}", style="bold red")
            sys.exit(1)


if __name__ == '__main__':
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n🛑 Operation cancelled by user", style="bold red")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n❌ Unexpected error: {e}", style="bold red")
        sys.exit(1)
