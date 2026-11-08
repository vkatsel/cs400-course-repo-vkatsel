# Course Reflection — Languages and Compilers Design

### 1. Most Useful Features or Idioms

One of the most useful concepts for me was learning how member functions and the `this` pointer work in Week 7. Before the course, I had no idea that the method were just functions where the compiler implicitly passes the struct's pointer as the first argument. 

---

### 2. Features Not Covered Properly
From the basic-level things, I think we should have covered string types a bit more. We have them allowed only inside print(...) function, but can't assign them to variable or pass to functions. That's a very interesting topic, I think we should spend a bit more time working with them. 

---

### 3. Three Surprising Insights About Languages and Compilers

1. The language lexer turned out to be just a finite state machine. Honestly, when you think of a programming language lexer you would expect something more complex, but it ended up being just a state machine.
2. The visitor pattern is actually a beautiful solution and pattern. As we wrote it one time, we didn't have to multiply the code for different things, we just could extend it and add logic on top, as every node has it's way of accepting the visitor.
3. The optimization can be done with just a use counter in the foundation. Also some sorts of things you think are complex, but actually are elegant in its simplicity. Of course, we are to look if the method has effect or deal with specific cases when a variable calls itself, but on the simplest level we're just checking if someone is reading/calling something multiple times.

---

### 4. Concepts or Approaches Still Not Clear Enough

It still remained somewhat unclear how to properly handle cyclic dependencis when optimizing the code. In Week 9, the UseCounter worked well for linear dead code but failed on cycles, when an unused variable updated itself or two unused functions were calling each other. I understand that this is a complex problem and was not expected to be solved, however it would be good to know. 

---

### 5. Ideas and Suggestions for Course Content

The course looks good, only small suggestions. First of all, (I know it was my bad) recommend splitiing the compiler.py into modules. I didn't do so, because for some reason I thought that by demands everything should live in one file, and by the end of the course had a one big file with thousands of lines.

Also, Early Birds policy would be great for this course assignments, as you can see what your mistakes were, analyze them and try to improve both your language and grade.

But in general, after each and every of the courses the 'magic' in my head went away and I ended up maybe not remembering all the nuances, but having a solid mental model of how things function in computers. Thank you for all the courses and guidance!
