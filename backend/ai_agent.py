import json
import re
from datetime import datetime
import random

class AIAgent:
    def __init__(self, database, file_analyzer):
        self.db = database
        self.file_analyzer = file_analyzer
        
        # Knowledge base for different topics
        self.knowledge_base = {
            'python': {
                'keywords': ['python', 'def ', 'import ', 'class ', 'list', 'dict', 'function'],
                'responses': self._get_python_response
            },
            'web': {
                'keywords': ['html', 'css', 'javascript', 'react', 'vue', 'angular', 'website'],
                'responses': self._get_web_response
            },
            'data': {
                'keywords': ['data', 'analysis', 'csv', 'excel', 'pandas', 'numpy', 'visualization'],
                'responses': self._get_data_response
            },
            'file': {
                'keywords': ['file', 'upload', 'document', 'pdf', 'image', 'analyze'],
                'responses': self._get_file_response
            },
            'system': {
                'keywords': ['help', 'how to', 'what can', 'assist', 'support'],
                'responses': self._get_system_response
            },
            'math': {
                'keywords': ['calculate', 'math', 'equation', 'solve', 'formula'],
                'responses': self._get_math_response
            }
        }
    
    def process_query(self, user_id, session_id, query, context=None):
        """Process user query and generate AI response"""
        # Save user query to history
        self.db.save_chat_message(user_id, session_id, query, is_user=True)
        
        # Analyze query
        query_lower = query.lower()
        topic = self._identify_topic(query_lower)
        
        # Get response based on topic
        if topic in self.knowledge_base:
            response = self.knowledge_base[topic]['responses'](query, context)
        else:
            response = self._get_general_response(query)
        
        # Format response
        formatted_response = self._format_response(response)
        
        # Save AI response to history
        self.db.save_chat_message(user_id, session_id, formatted_response, is_user=False)
        
        return formatted_response
    
    def _identify_topic(self, query):
        """Identify the main topic of the query"""
        scores = {}
        
        for topic, data in self.knowledge_base.items():
            score = 0
            for keyword in data['keywords']:
                if keyword in query:
                    score += 1
            scores[topic] = score
        
        # Return topic with highest score
        max_topic = max(scores, key=scores.get)
        return max_topic if scores[max_topic] > 0 else 'general'
    
    def _get_python_response(self, query, context):
        """Generate response for Python-related queries"""
        responses = [
            "Here's a Python solution for that:",
            "In Python, you can do this:",
            "Here's how to implement that in Python:",
            "Python provides several ways to handle this:"
        ]
        
        code_examples = {
            'list': "my_list = [1, 2, 3, 4, 5]\nfiltered = [x for x in my_list if x > 2]",
            'dict': "my_dict = {'key1': 'value1', 'key2': 'value2'}\nfor key, value in my_dict.items():\n    print(f'{key}: {value}')",
            'function': "def my_function(param1, param2):\n    result = param1 + param2\n    return result",
            'class': "class MyClass:\n    def __init__(self, name):\n        self.name = name\n    \n    def greet(self):\n        return f'Hello, {self.name}!'"
        }
        
        response = random.choice(responses)
        
        # Check for specific Python concepts
        if 'list' in query.lower():
            code = code_examples['list']
        elif 'dict' in query.lower() or 'dictionary' in query.lower():
            code = code_examples['dict']
        elif 'function' in query.lower():
            code = code_examples['function']
        elif 'class' in query.lower():
            code = code_examples['class']
        else:
            # Default Python code example
            code = '''def example_function(data):
    """Process data and return result"""
    if not data:
        return None
    
    # Process data here
    result = sum(data) / len(data)
    return result'''
        
        return f"{response}\n\n```python\n{code}\n```"
    
    def _get_web_response(self, query, context):
        """Generate response for web development queries"""
        if 'html' in query.lower():
            return """Here's an HTML structure for that:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header>
        <nav>
            <!-- Navigation content -->
        </nav>
    </header>
    <main>
        <!-- Main content -->
    </main>
    <footer>
        <!-- Footer content -->
    </footer>
    <script src="script.js"></script>
</body>
</html>```"""
        
        elif 'css' in query.lower():
            return """Here are some CSS techniques:

```css
/* Modern CSS with flexbox */
.container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    padding: 2rem;
}

/* Responsive design */
@media (max-width: 768px) {
    .container {
        flex-direction: column;
        padding: 1rem;
    }
}

/* CSS Grid layout */
.grid-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 1.5rem;
}```"""
        
        elif 'javascript' in query.lower() or 'js' in query.lower():
            return """Here's a JavaScript example:

```javascript
// Modern JavaScript with async/await
async function fetchData(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching data:', error);
        return null;
    }
}

// Event handling
document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('myButton');
    button.addEventListener('click', handleClick);
});

function handleClick(event) {
    event.preventDefault();
    // Handle click logic
}```"""
        
        return "I can help with web development topics including HTML, CSS, JavaScript, and frameworks. What specific area do you need assistance with?"
    
    def _get_data_response(self, query, context):
        """Generate response for data analysis queries"""
        if 'pandas' in query.lower():
            return """Here's a Pandas data analysis example:

```python
import pandas as pd
import numpy as np

# Load data
df = pd.read_csv('data.csv')

# Basic exploration
print(f"Shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
print(f"\\nData Types:\\n{df.dtypes}")
print(f"\\nMissing values:\\n{df.isnull().sum()}")

# Data cleaning
df_clean = df.dropna()  # Remove missing values
df_clean = df_clean.drop_duplicates()  # Remove duplicates

# Basic analysis
numeric_cols = df_clean.select_dtypes(include=[np.number]).columns
if len(numeric_cols) > 0:
    stats = df_clean[numeric_cols].describe()
    print(f"\\nStatistics:\\n{stats}")

# Grouping and aggregation
if 'category' in df_clean.columns:
    grouped = df_clean.groupby('category').agg({
        'value': ['mean', 'median', 'std', 'count']
    })
    print(f"\\nGrouped statistics:\\n{grouped}")```"""
        
        return "I can help with data analysis using Python libraries like Pandas, NumPy, and visualization tools. Would you like help with data cleaning, analysis, or visualization?"
    
    def _get_file_response(self, query, context):
        """Generate response for file-related queries"""
        user_files = self.db.get_user_files(context['user_id']) if context else []
        
        if 'list' in query.lower() or 'show' in query.lower() or 'files' in query.lower():
            if user_files:
                file_list = "\\n".join([f"- {f['filename']} ({f['file_type']}, {f['size']} bytes)" 
                                       for f in user_files[:5]])
                return f"Here are your recent files:\n\n{file_list}"
            else:
                return "You haven't uploaded any files yet. You can upload files using the upload button."
        
        return "I can help you analyze files, extract information, and work with different file formats. What would you like to do with your files?"
    
    def _get_system_response(self, query, context):
        """Generate response for system/help queries"""
        help_text = """I'm your Local AI Assistant. Here's what I can help you with:

**1. Code Assistance**
- Python, JavaScript, HTML/CSS
- Debugging and optimization
- Algorithm implementation

**2. Data Analysis**
- CSV, Excel, JSON file analysis
- Data cleaning and transformation
- Statistical analysis

**3. File Management**
- Upload and analyze files (PDF, images, documents)
- Extract information from files
- File organization

**4. General Knowledge**
- Technical explanations
- Problem-solving strategies
- Best practices

**5. System Commands**
- `list files` - Show your uploaded files
- `analyze [filename]` - Analyze a specific file
- `clear chat` - Clear current conversation
- `help` - Show this help message

Just ask me anything, and I'll do my best to help!"""
        
        return help_text
    
    def _get_math_response(self, query, context):
        """Generate response for math-related queries"""
        # Extract numbers and operations from query
        numbers = re.findall(r'\d+\.?\d*', query)
        
        if numbers and ('add' in query or 'sum' in query or '+' in query):
            nums = [float(n) for n in numbers]
            result = sum(nums)
            return f"The sum of {', '.join(map(str, nums))} is **{result}**"
        
        elif numbers and ('multiply' in query or 'product' in query or '*' in query or '×' in query):
            nums = [float(n) for n in numbers]
            result = 1
            for n in nums:
                result *= n
            return f"The product of {', '.join(map(str, nums))} is **{result}**"
        
        elif numbers and ('divide' in query or 'quotient' in query or '/' in query or '÷' in query):
            if len(numbers) >= 2:
                result = float(numbers[0]) / float(numbers[1])
                return f"{numbers[0]} ÷ {numbers[1]} = **{result}**"
        
        elif 'factorial' in query.lower():
            return """The factorial function calculates the product of all positive integers up to n.

**Mathematical Definition:**
n! = n × (n-1) × (n-2) × ... × 2 × 1

**Python Implementation:**
```python
def factorial(n):
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    if n == 0:
        return 1
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

# Example
print(factorial(5))  # Output: 120
print(factorial(0))  # Output: 1```"""
        
        return "I can help with mathematical calculations, formulas, and algorithm implementations. What specific math problem are you working on?"
    
    def _get_general_response(self, query):
        """Generate response for general queries"""
        general_responses = [
            f"I understand you're asking about: {query}. Could you provide more details about what specifically you need help with?",
            f"Interesting question about '{query}'. I can help you with technical aspects, implementation details, or analysis of this topic.",
            f"Regarding '{query}', I can assist with code implementation, data analysis, or providing explanations. What aspect would you like to focus on?",
            f"I've noted your query about '{query}'. Let me know if you need coding help, data analysis, or explanations on this topic."
        ]
        
        return random.choice(general_responses)
    
    def _format_response(self, response):
        """Format the response with proper structure"""
        # Add timestamp
        timestamp = datetime.now().strftime("%I:%M %p")
        
        # Format code blocks if present
        if '```' in response:
            # Already formatted with code blocks
            return response
        
        # For longer responses, add structure
        if len(response) > 200:
            return f"{response}\n\n*Generated at {timestamp}*"
        
        return response