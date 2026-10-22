import turtle as t
planets = [["O","X","O"],
           ["X","O","X"],
           ["O","X","O"]]
row = len(planets)
col = len(planets[0])
for j in range(row):
    for i in range(col):
        t.penup()
        t.goto(0+25*i, 0-25*j)
        t.pendown()
        t.write(planets[j][i])
print(planets)
