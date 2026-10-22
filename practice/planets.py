import turtle as t
planets = [["Mercury", 4879, "Gray"],["Venus", 12184, "Pale Yellow"],["Mars",6779,"Red"],["Jupiter",139822,"Orange"],["Saturn",116464,"Gold"],["Uranus",50724,"Pale Blue"],["Neptune",49244,"Blue"]]
row = len(planets)
col = len(planets[0])
for j in range(row):
    for i in range(col):
        t.penup()
        t.goto(0+50*i, 0-50*j)
        t.pendown()
        t.write(planets[j][i])
print(planets)
