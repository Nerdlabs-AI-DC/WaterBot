"""
WaterBot - AI Discord bot manager
Copyright (C) 2026  Nerdlabs AI

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import json
import os
import re
import shutil
import tempfile
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any
from packaging import version

GITHUB_REPO = "Nerdlabs-AI-DC/WaterBot"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"

APP_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get("WATERBOT_DATA_DIR", str(APP_DIR / ".." / ".local" / "share" / "waterbot")))
UPDATE_STATE_FILE = DATA_DIR / "update_state.json"


class UpdateError(Exception):
    pass


def get_current_version() -> str:
    try:
        from src import __version__
        return __version__
    except ImportError:
        pass
    
    init_py = APP_DIR / "src" / "__init__.py"
    if init_py.exists():
        try:
            with open(init_py) as f:
                match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", f.read())
                if match:
                    return match.group(1)
        except Exception:
            pass
    
    return "unknown"


def fetch_latest_release(include_prereleases: bool = True) -> Optional[Dict[str, Any]]:
    headers = {'User-Agent': 'WaterBot-Update-Checker/1.0', 'Accept': 'application/vnd.github.v3+json'}
    
    try:
        req = urllib.request.Request(GITHUB_RELEASES_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            releases = json.loads(response.read().decode('utf-8'))
        
        if not releases:
            req = urllib.request.Request(GITHUB_API_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode('utf-8'))
        
        if not include_prereleases:
            for release in releases:
                if not release.get('prerelease', False):
                    return release
        
        return releases[0]
    except urllib.error.HTTPError as e:
        if e.code == 403:
            try:
                req = urllib.request.Request(GITHUB_RELEASES_URL)
                with urllib.request.urlopen(req, timeout=15) as response:
                    releases = json.loads(response.read().decode('utf-8'))
                    if releases:
                        return releases[0]
            except Exception:
                pass
        raise UpdateError(f"Failed to fetch release: HTTP {e.code} - {e.reason}")
    except Exception as e:
        raise UpdateError(f"Failed to fetch release: {str(e)}")
    return None


def fetch_all_releases() -> list:
    try:
        headers = {'User-Agent': 'WaterBot-Update-Checker/1.0', 'Accept': 'application/vnd.github.v3+json'}
        req = urllib.request.Request(GITHUB_RELEASES_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8')) or []
    except Exception:
        return []


def compare_versions(current: str, latest: str) -> int:
    current = current.lstrip('vV')
    latest = latest.lstrip('vV')
    
    try:
        current_ver = version.parse(current)
        latest_ver = version.parse(latest)
        if current_ver < latest_ver:
            return -1
        elif current_ver > latest_ver:
            return 1
        return 0
    except Exception:
        if current < latest:
            return -1
        elif current > latest:
            return 1
        return 0


def is_update_available(include_prereleases: bool = True) -> Optional[Dict[str, Any]]:
    try:
        current_version = get_current_version()
        release = fetch_latest_release(include_prereleases=include_prereleases)
        
        if not release:
            return None
        
        latest_version = release.get('tag_name', release.get('name', 'unknown')).lstrip('vV')
        current_version = current_version.lstrip('vV')
        available = compare_versions(current_version, latest_version) < 0
        
        return {
            'current_version': current_version,
            'latest_version': latest_version,
            'release': release,
            'available': available,
            'is_prerelease': release.get('prerelease', False)
        }
    except Exception:
        return None


def get_release_download_url(release: Dict[str, Any]) -> Optional[str]:
    for asset in release.get('assets', []):
        name = asset.get('name', '').lower()
        if 'source' in name and name.endswith('.zip'):
            return asset.get('browser_download_url')
        if 'source' in name and name.endswith('.tar.gz'):
            return asset.get('browser_download_url')
    
    return release.get('zipball_url') or release.get('tarball_url')


def download_update(download_url: str, temp_dir: Path) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    filename = download_url.split('/')[-1]
    dest_path = temp_dir / filename
    
    try:
        import requests
        response = requests.get(download_url, stream=True, timeout=30)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return dest_path
    except ImportError:
        pass
    
    req = urllib.request.Request(download_url)
    with urllib.request.urlopen(req, timeout=30) as response:
        with open(dest_path, 'wb') as f:
            shutil.copyfileobj(response, f)
    return dest_path


def extract_update(archive_path: Path, extract_dir: Path) -> Path:
    import zipfile
    import tarfile
    
    extract_dir.mkdir(parents=True, exist_ok=True)
    
    def detect_archive_type(filepath):
        with open(filepath, 'rb') as f:
            header = f.read(512)
        if header[:2] == b'PK':
            return 'zip'
        if header[:2] == b'\x1f\x8b' or b'ustar' in header:
            return 'tar.gz'
        suffix = filepath.suffix.lower()
        if suffix == '.zip':
            return 'zip'
        if suffix in ('.tar.gz', '.tgz', '.tar'):
            return 'tar.gz'
        return None
    
    archive_type = detect_archive_type(archive_path)
    
    if archive_type == 'zip':
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            top_level_dir = None
            for name in zip_ref.namelist():
                if '/' in name:
                    top_level_dir = name.split('/')[0]
                    break
            zip_ref.extractall(extract_dir)
            if top_level_dir:
                return extract_dir / top_level_dir
            return extract_dir
    
    if archive_type == 'tar.gz':
        with tarfile.open(archive_path, 'r:gz') as tar_ref:
            tar_ref.extractall(extract_dir)
            if tar_ref.getmembers():
                return extract_dir / tar_ref.getmembers()[0].name.split('/')[0]
            return extract_dir
    
    raise UpdateError(f"Unsupported archive format: {archive_path.suffix}")


def perform_update(release: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
    update_state = {
        'status': 'starting',
        'progress': 0,
        'error': None,
        'started_at': time.time(),
        'completed_at': None
    }
    
    try:
        UPDATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(UPDATE_STATE_FILE, 'w') as f:
            json.dump(update_state, f)
        
        download_url = get_release_download_url(release)
        if not download_url:
            raise UpdateError("No download URL found for release")
        
        if progress_callback:
            progress_callback(5, "Preparing update...")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            if progress_callback:
                progress_callback(10, "Downloading update...")
            
            archive_path = download_update(download_url, temp_path)
            
            if progress_callback:
                progress_callback(40, "Extracting update...")
            
            extracted_dir = extract_update(archive_path, temp_path / "extracted")
            
            if not extracted_dir.exists():
                raise UpdateError("Extraction failed - no directory found")
            
            install_dir = APP_DIR
            
            if progress_callback:
                progress_callback(60, "Backing up current installation...")
            
            backup_dir = DATA_DIR / "backup" / f"waterbot_backup_{int(time.time())}"
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            
            if install_dir.exists():
                shutil.copytree(install_dir, backup_dir, dirs_exist_ok=True)
            
            if progress_callback:
                progress_callback(70, "Installing new version...")
            
            copy_update_files(extracted_dir, install_dir)
            
            if progress_callback:
                progress_callback(90, "Cleaning up...")
            
            cleanup_old_files(install_dir, extracted_dir)
            
            update_state['status'] = 'completed'
            update_state['progress'] = 100
            update_state['completed_at'] = time.time()
            update_state['version'] = release.get('tag_name', release.get('name', 'unknown'))
            update_state['backup_dir'] = str(backup_dir)
            
            with open(UPDATE_STATE_FILE, 'w') as f:
                json.dump(update_state, f)
            
            if progress_callback:
                progress_callback(100, "Update completed!")
            
            return {
                'success': True,
                'message': 'Update completed successfully',
                'version': release.get('tag_name', release.get('name', 'unknown')),
                'backup_dir': str(backup_dir),
                'restart_required': True
            }
            
    except Exception as e:
        update_state['status'] = 'failed'
        update_state['error'] = str(e)
        update_state['completed_at'] = time.time()
        
        with open(UPDATE_STATE_FILE, 'w') as f:
            json.dump(update_state, f)
        
        return {
            'success': False,
            'message': str(e),
            'error': str(e)
        }


def copy_update_files(source_dir: Path, dest_dir: Path):
    for item in source_dir.iterdir():
        dest_item = dest_dir / item.name
        
        if item.is_dir():
            if item.name.startswith('.') and item.name != '.git':
                continue
            dest_item.mkdir(exist_ok=True)
            copy_update_files(item, dest_item)
        else:
            shutil.copy2(item, dest_item)


def cleanup_old_files(dest_dir: Path, source_dir: Path):
    source_files = set()
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            rel_path = os.path.relpath(root, source_dir)
            source_files.add(f if rel_path == '.' else f"{rel_path}/{f}")
    
    for root, dirs, files in os.walk(dest_dir):
        for f in files:
            rel_path = os.path.relpath(root, dest_dir)
            file_path = f if rel_path == '.' else f"{rel_path}/{f}"
            
            if file_path.startswith(('data/', '.venv/', '__pycache__')):
                continue
            
            if file_path not in source_files:
                try:
                    (Path(root) / f).unlink()
                except Exception:
                    pass


def get_update_state() -> Dict[str, Any]:
    if UPDATE_STATE_FILE.exists():
        try:
            with open(UPDATE_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {'status': 'unknown', 'error': 'Failed to read state file'}
    return {'status': 'not_started'}


def clear_update_state():
    try:
        if UPDATE_STATE_FILE.exists():
            UPDATE_STATE_FILE.unlink()
    except Exception:
        pass


def rollback_update() -> Dict[str, Any]:
    state = get_update_state()
    backup_dir = state.get('backup_dir')
    
    if not backup_dir or not Path(backup_dir).exists():
        return {'success': False, 'message': 'No backup found for rollback'}
    
    try:
        install_dir = APP_DIR
        backup_path = Path(backup_dir)
        
        if install_dir.exists():
            shutil.rmtree(install_dir)
        
        shutil.copytree(backup_path, install_dir)
        clear_update_state()
        
        return {
            'success': True,
            'message': 'Rollback completed successfully',
            'version': get_current_version()
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def is_update_in_progress() -> bool:
    state = get_update_state()
    return state.get('status') == 'starting'


class UpdateChecker:
    """Periodic update checker that runs in the background."""
    
    def __init__(self, check_interval: int = 3600, callback=None, include_prereleases: bool = True):
        self.check_interval = check_interval
        self.callback = callback
        self.include_prereleases = include_prereleases
        self._running = False
        self._thread = None
        self._last_check = 0
        self._latest_release = None
    
    def start(self):
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _run(self):
        import time as time_module
        
        while self._running:
            try:
                result = is_update_available(include_prereleases=self.include_prereleases)
                self._latest_release = result
                
                if result and result.get('available'):
                    if self.callback:
                        self.callback(
                            available=True,
                            current_version=result.get('current_version'),
                            latest_version=result.get('latest_version'),
                            release=result.get('release')
                        )
                
                wait_time = self.check_interval
                while self._running and wait_time > 0:
                    time_module.sleep(min(wait_time, 1))
                    wait_time -= 1
                    
            except Exception as e:
                print(f"Update checker error: {e}")
                wait_time = min(self.check_interval, 300)
                while self._running and wait_time > 0:
                    time_module.sleep(min(wait_time, 1))
                    wait_time -= 1
    
    def check_now(self):
        try:
            result = is_update_available(include_prereleases=self.include_prereleases)
            self._latest_release = result
            
            if self.callback and result:
                self.callback(
                    available=result.get('available', False),
                    current_version=result.get('current_version'),
                    latest_version=result.get('latest_version'),
                    release=result.get('release')
                )
            
            return result
        except Exception as e:
            print(f"Immediate update check error: {e}")
            return None
    
    def get_latest_release(self):
        return self._latest_release
