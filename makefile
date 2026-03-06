build:
	rm -rf build
	rm -rf duka_smartfan_sdk.egg-info
	rm -rf dist
	python -m build

clean:
	rm -rf build
	rm -rf duka_smartfan_sdk.egg-info
	rm -rf dist

upload:
	twine upload --repository pypi dist/*
