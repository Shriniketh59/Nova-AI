class Node:
    def __init__(self, value):
        self.value = value
        self.next = None

class Stack:
    def __init__(self):
        self.top = None
        self.size = 0

    def push(self, value):
        new_node = Node(value)
        if not self.top:
            self.top = new_node
        else:
            new_node.next = self.top
            self.top = new_node
        self.size += 1

    def pop(self):
        if not self.top:
            raise ValueError("Stack is empty")
        value = self.top.value
        self.top = self.top.next
        self.size -= 1
        return value

    def peek(self):
        if not self.top:
            raise ValueError("Stack is empty")
        return self.top.value

# Example usage:
stack = Stack()
print(stack.peek())  # Output: None (empty stack)
stack.push(5)
stack.push(10)
print(stack.pop())  # Output: 10
print(stack.peek())  # Output: 5