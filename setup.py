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

from setuptools import setup, find_packages
from pathlib import Path
from src import __version__

readme_file = Path(__file__).parent / "README.md"
long_description = ""
if readme_file.exists():
    with open(readme_file, encoding="utf-8") as f:
        long_description = f.read()

setup(
    name="waterbot",
    version=__version__,
    description="WaterBot - AI Discord bot manager",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Nerdlabs AI",
    url="https://github.com/Nerdlabs-AI-DC/WaterBot",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "flask",
        "flask-cors",
        "flask-session",
        "psutil",
        "gunicorn",
        "setuptools",
        "packaging",
        "discord",
        "requests",
        "openai",
        "cryptography",
        "numpy",
        "openrouter",
        "matplotlib",
    ],
    entry_points={
        "console_scripts": [
            "waterbot=src.launcher:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Environment :: Console",
        "Natural Language :: English"
    ],
)
