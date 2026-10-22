import numpy as np
from ast import literal_eval
matrix1 = np.array(literal_eval(input("Matrix 1: ")))
matrix2 = np.array(literal_eval(input("Matrix 2: ")))
print("Matrix 1 * Matrix 2:", matrix1 @ matrix2)
