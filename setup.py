from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in __init__.py
from subscriptions2 import __version__ as version

setup(
	name="subscriptions2",
	version=version,
	description="Subscriptions2",
	author="Richard Case",
	author_email="richard@casesolved.co.uk",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
