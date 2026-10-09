from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST-Lab/src'),str(ROOT/'MCP/CST-CAD/src'),str(ROOT/'MCP/CST-Brain/src')]
