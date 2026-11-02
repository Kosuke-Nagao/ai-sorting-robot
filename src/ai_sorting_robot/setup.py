from setuptools import find_packages, setup


package_name = "ai_sorting_robot"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="honor",
    maintainer_email="student@example.com",
    description="Natural-language sorting robot simulation.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "spawn_workcell = ai_sorting_robot.spawn_workcell:main",
            "pick_place = ai_sorting_robot.pick_place:main",
            "natural_sort = ai_sorting_robot.natural_sort:main",
        ],
    },
)
