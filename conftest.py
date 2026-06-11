# conftest.py —— 让 pytest 从项目根解析 schemas / graphs / services 等包
import os
import sys

'''
pytest 在真正去碰你的测试文件之前，会先像雷达一样扫描当前目录及其父目录，
寻找有没有一个叫 conftest.py 的文件。这是一个被 pytest 硬编码写死在底层逻辑里的特殊文件名。
'''
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    # sys.path.insert(0, PROJECT_ROOT)：如果没有，就使用 insert(0, ...)，把你的项目根目录强行插到列表的最顶端（索引为 0 的位置）。