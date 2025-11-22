# code_views.py

# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.contrib.admin.views.decorators import staff_member_required

# REST Framework imports
from rest_framework import generics
from App.serializers import ProblemSerializer

# Core models and execution
from App.models import Problem

# from App.code_runner.code_runner3 import execute_code  # docker

from App.code_runner.code_runner import execute_code
from App.mongo import log_submission_attempt, get_comments_for_problem, save_comment

# Standard library
import json, re, textwrap, time


# ------------------------
# ✅ Language Map
# ------------------------
language_map = {
    "python": "python",
    "cpp": "cpp",
    "java": "java",
    "c": "c",
}


# ------------------------
# ✅ Problem APIs
# ------------------------
class ProblemListAPIView(generics.ListAPIView):
    queryset = Problem.objects.all()
    serializer_class = ProblemSerializer


class ProblemDetailAPIView(generics.RetrieveAPIView):
    queryset = Problem.objects.all()
    serializer_class = ProblemSerializer
    lookup_field = "slug"


# ------------------------
# ✅ Monaco Editor Code Compilation
# ------------------------
def compile_code_monaco(request, slug=None):
    print("[INFO] compile_code_monaco view called")
    problem = get_object_or_404(Problem, slug=slug) if slug else None
    selected_language = request.POST.get("language", "python").lower()
    # Map language for backend processing
    backend_language = language_map.get(selected_language, "python")

    # Default templates if no problem is specified
    default_templates = {
        "python": "# Write your Python code here\ndef solve():\n    # Your solution goes here\n    pass\n\nif __name__ == '__main__':\n    result = solve()\n    print(result)",
        "cpp": '#include <iostream>\n#include <vector>\n#include <string>\nusing namespace std;\n\nint main() {\n    // Your C++ code here\n    cout << "Hello, World!" << endl;\n    return 0;\n}',
        "java": 'public class Main {\n    public static void main(String[] args) {\n        // Your Java code here\n        System.out.println("Hello, World!");\n    }\n}',
        "c": '#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\nint main() {\n    // Your C code here\n    printf("Hello, World!\\n");\n    return 0;\n}',
    }

    # Define default starter code templates for each language
    starter_codes = {
        "python": '# Write your code here\nprint("Hello, World!")',
        "cpp": '# Write your code here\n#include <iostream>\nint main(){\n    std::cout << "Hello, World!" << std::endl;\n    return 0;\n}',
        "java": '# Write your code here\npublic class Main {\n    public static void main(String[] args){\n        System.out.println("Hello, World!");\n    }\n}',
        "c": '# Write your code here\n#include <stdio.h>\nint main(){\n    printf("Hello, World!\\n");\n    return 0;\n}',
    }

    starter_code = (
        get_starter_code(problem, backend_language)
        if problem
        else default_templates.get(
            backend_language, "# Write your code here\nprint('Hello World')"
        )
    )

    starter_codes = {}
    for lang_key, lang_name in language_map.items():
        if problem:
            starter_codes[lang_key] = get_starter_code(problem, lang_name)
        else:
            starter_codes[lang_key] = default_templates.get(lang_key, "")

    comments = get_comments_for_problem(slug) if problem else []

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        action = request.POST.get("action", "run")

        print(f"🎯 POST request received - Action: '{action}'")
        print(f"📄 Code length: {len(code)} characters")

        if not request.user.is_authenticated:
            return render(
                request,
                "compiler/index.html",
                {
                    "error": "⚠️ You must be logged in to run or submit code.",
                    "problem": problem,
                    "code": code or starter_code,
                    "language": selected_language,
                    "starter_codes": starter_codes,
                    "not_logged_in": True,
                    "comments": comments,
                },
            )

        if not code.strip():
            return render(
                request,
                "compiler/index.html",
                {
                    "error": "No code submitted.",
                    "problem": problem,
                    "code": starter_code,
                    "language": selected_language,
                    "starter_codes": starter_codes,
                    "comments": comments,
                },
            )

        if action == "run":
            print("🏃 Processing RUN action - calling run_examples()")
            results = run_examples(problem, code.strip(), backend_language)
            return render(
                request,
                "compiler/index.html",
                {
                    "code": code,
                    "language": selected_language,
                    "problem": problem,
                    "action": "run",
                    "run_results": results,
                    "starter_codes": starter_codes,
                    "comments": comments,
                },
            )

        elif action == "submit":
            print("📝 Processing SUBMIT action - calling submit_test_cases()")
            results, passed_cases, total_cases = submit_test_cases(
                problem,
                code.strip(),
                backend_language,
                request.user.id if request.user.is_authenticated else None,
            )
            all_passed = passed_cases == total_cases
            return render(
                request,
                "compiler/index.html",
                {
                    "code": code,
                    "language": selected_language,
                    "problem": problem,
                    "action": "submit",
                    "all_passed": all_passed,
                    "total_cases": total_cases,
                    "passed_cases": passed_cases,
                    "failed_case_number": passed_cases + 1 if not all_passed else None,
                    "run_results": results,
                    "starter_codes": starter_codes,
                    "comments": comments,
                },
            )

    return render(
        request,
        "compiler/index.html",
        {
            "code": starter_code,
            "problem": problem,
            "language": selected_language if request.method == "POST" else "python",
            "starter_codes": starter_codes,
            "comments": comments,
        },
    )


# ------------------------
# ✅ Basic Code Runner (no problem)
# ------------------------
@csrf_exempt
def compile_code_basic(request):
    print("from new Views folder")
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        language_key = request.POST.get("language", "python").lower()
        custom_input = request.POST.get("input", "")
        language = language_map.get(language_key, "python")

        if not code:
            return render(
                request,
                "compiler/index.html",
                {
                    "error": "No code submitted.",
                    "code": "",
                    "language": language,
                    "input": custom_input,
                    "output": "",
                },
            )

        # Automatically append driver code for Python
        if language.lower() == "python":
            # Only add driver if not present
            if "if __name__ == '__main__'" not in code:
                driver_code = "\nif __name__ == '__main__':\n    result = solve()\n    print(result)"
                code_to_run = code.strip() + driver_code
            else:
                code_to_run = code
        else:
            code_to_run = code

        result = execute_code(code_to_run, language=language, input_data=custom_input)

        return render(
            request,
            "compiler/index.html",
            {
                "code": code,  # Show only user code
                "language": language,
                "input": custom_input,
                "output": result.strip(),
                "action": "run",
            },
        )

    # Minimal starter code templates for each language
    starter_codes = {
        "python": '# Write your code here\nprint("Hello, World!")',
        "cpp": '#include <iostream>\nusing namespace std;\n// Write your code here\ncout << "Hello, World!" << endl;',
        "java": '// Write your code here\nSystem.out.println("Hello, World!");',
        "c": '// Write your code here\nprintf("Hello, World!\\n");',
    }

    return render(
        request,
        "compiler/index.html",
        {
            "code": starter_codes["python"],
            "language": "python",
            "input": "",
            "output": "",
            "starter_codes": starter_codes,
        },
    )


# ------------------------
# ✅ Utility: Starter Code Loader
# ------------------------
def get_starter_code(problem, language):
    slug = getattr(problem, "slug", "fallback_function")

    try:
        code = problem.starter_code.get_code(language, slug=slug)
        if not code or not code.strip():
            raise ValueError("Empty code")
        return code
    except:
        # Better fallback templates for each language
        fallback_templates = {
            "python": f"def {slug.replace('-', '_')}(input_data):\n    # Write your code here\n    pass",
            "java": f"public class Main {{\n    public Object {slug.replace('-', '_')}(Object input) {{\n        // Write your code here\n        return null;\n    }}\n}}",
            "cpp": f'#include <iostream>\n#include <vector>\n#include <string>\nusing namespace std;\n\nstring {slug.replace("-", "_")}(string input) {{\n    // Write your code here\n    return "";\n}}',
            "c": f'#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\nchar* {slug.replace("-", "_")}(char* input) {{\n    // Write your code here\n    return "result";\n}}',
        }

        return fallback_templates.get(
            language, f"// Language '{language}' not supported."
        )


# ------------------------
# ✅ Utility: Extract Function Name for Different Languages
# ------------------------
def extract_python_function_name(code, fallback="function_name"):
    match = re.search(r"def\s+(\w+)\s*\(", code)
    return match.group(1) if match else fallback


def extract_java_class_method_name(code, fallback="solution"):
    # Look for public method in Java code
    match = re.search(r"public\s+\w+\s+(\w+)\s*\(", code)
    return match.group(1) if match else fallback


def extract_cpp_function_name(code, fallback="solution"):
    # Look for function definition in C++
    match = re.search(r"\w+\s+(\w+)\s*\([^)]*\)\s*{", code)
    return match.group(1) if match else fallback


def extract_c_function_name(code, fallback="solution"):
    # Look for function definition in C
    match = re.search(r"\w+\*?\s+(\w+)\s*\([^)]*\)\s*{", code)
    return match.group(1) if match else fallback


# ------------------------
# ✅ Utility: Generate Driver Code for Different Languages
# ------------------------
def generate_driver_code(language, func_name, args, slug):
    """Generate driver code for different programming languages"""

    if language == "python":
        return f"""
import json
if __name__ == "__main__":
    try:
        result = {func_name}(*{json.dumps(args)})
    except Exception as e:
        result = str(e)
    print(json.dumps(result))
"""

    elif language == "cpp":
        # Convert Python args to C++ format
        cpp_args = []
        for arg in args:
            if isinstance(arg, str):
                cpp_args.append(f'"{arg}"')
            elif isinstance(arg, list):
                if all(isinstance(x, int) for x in arg):
                    cpp_args.append("{" + ", ".join(map(str, arg)) + "}")
                else:
                    cpp_args.append('{"' + '", "'.join(map(str, arg)) + '"}')
            else:
                cpp_args.append(str(arg))

        args_str = ", ".join(cpp_args)

        return f"""
#include <iostream>
#include <vector>
#include <string>
#include <sstream>
using namespace std;

int main() {{
    try {{
        auto result = {func_name}({args_str});
        cout << result << endl;
    }} catch (const exception& e) {{
        cout << "Error: " << e.what() << endl;
    }}
    return 0;
}}
"""

    elif language == "java":
        # Convert Python args to Java format
        java_args = []
        for arg in args:
            if isinstance(arg, str):
                java_args.append(f'"{arg}"')
            elif isinstance(arg, list):
                if all(isinstance(x, int) for x in arg):
                    java_args.append("new int[]{" + ", ".join(map(str, arg)) + "}")
                else:
                    java_args.append(
                        'new String[]{"' + '", "'.join(map(str, arg)) + '"}'
                    )
            else:
                java_args.append(str(arg))

        args_str = ", ".join(java_args)

        # Simple Java driver code that appends main method inside the user's class
        return f"""

    public static void main(String[] args) {{
        Main solution = new Main();
        Object result = solution.{func_name}({args_str});
        System.out.println(result);
    }}
}}"""

    elif language == "c":
        # Convert Python args to C format
        c_args = []
        for arg in args:
            if isinstance(arg, str):
                c_args.append(f'"{arg}"')
            else:
                c_args.append(str(arg))

        args_str = ", ".join(c_args)

        return f"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main() {{
    char* result = {func_name}({args_str});
    printf("%s\\n", result);
    return 0;
}}
"""

    else:
        print(f"[WARNING] Unsupported language for driver code generation: {language}")
        return ""


# ------------------------
# ✅ Utility: Get Function Name Based on Language
# ------------------------
def get_function_name(starter_code, language, fallback):
    """Extract function name based on the programming language"""
    if language == "python":
        return extract_python_function_name(starter_code, fallback)
    elif language == "java":
        return extract_java_class_method_name(starter_code, fallback)
    elif language == "cpp":
        return extract_cpp_function_name(starter_code, fallback)
    elif language == "c":
        return extract_c_function_name(starter_code, fallback)
    else:
        return fallback


# ------------------------
# ✅ Run Examples (per-case driver)
# ------------------------
def run_examples(problem, code, language):
    print(f"🔄 run_examples called for language: {language}")
    examples = getattr(problem, "examples_group", None)
    examples = examples.examples if examples else []

    inputs = [ex.get("input") for ex in examples if ex.get("input") is not None]
    expected_outputs = [
        ex.get("output") for ex in examples if ex.get("output") is not None
    ]

    # Get starter code for the specific language
    starter_code = problem.starter_code.get_code(language, slug=problem.slug)
    func_name = get_function_name(
        starter_code, language, fallback=problem.slug.replace("-", "_")
    )

    print(f"📝 Using function name: {func_name} for language: {language}")

    results = []
    for i, (input_val, expected_output) in enumerate(
        zip(inputs, expected_outputs), start=1
    ):
        try:
            input_dict = (
                json.loads(input_val) if isinstance(input_val, str) else input_val
            )
            args = [input_dict[key] for key in sorted(input_dict.keys(), key=int)]
        except Exception as e:
            print(f"[ERROR] run_examples({i}): {e}")
            args = []

        # Generate driver code based on language
        driver_code = generate_driver_code(language, func_name, args, problem.slug)

        if not driver_code:
            print(f"[ERROR] Unsupported language: {language}")
            results.append(
                {
                    "input": input_val,
                    "expected": expected_output,
                    "output": f"Unsupported language: {language}",
                    "passed": False,
                    "case_number": i,
                }
            )
            continue

        print(f"🚀 Generated driver code for {language}:")
        print(f"{'='*50}")
        print(driver_code[:200] + "..." if len(driver_code) > 200 else driver_code)
        print(f"{'='*50}")

        if language == "java":
            # For Java, ensure class name is "Main" (required by Docker container)
            java_code = code.strip()
            # Replace "class Solution" with "class Main" if present
            java_code = re.sub(r"\bclass\s+Solution\b", "class Main", java_code)

            # Remove the last closing brace from user code and append driver code + closing brace
            user_code_without_last_brace = java_code.rstrip("}").rstrip()
            final_code = (
                user_code_without_last_brace + "\n" + textwrap.dedent(driver_code)
            )
        else:
            final_code = code.strip() + "\n\n" + textwrap.dedent(driver_code)

        result_output = execute_code(final_code, language=language, input_data="")

        try:
            output_lines = result_output.strip().splitlines()
            if not output_lines:
                output_val = "No output"
            else:
                output_line = output_lines[-1]

                # Parse output based on language
                if language == "python" or language == "c":
                    try:
                        output_val = json.loads(output_line)
                    except json.JSONDecodeError:
                        output_val = output_line
                else:
                    # For C++ and Java, the output is usually direct
                    output_val = output_line

                    # Try to convert to appropriate type if it's a number
                    try:
                        if "." in output_val:
                            output_val = float(output_val)
                        else:
                            output_val = int(output_val)
                    except (ValueError, TypeError):
                        # Keep as string if can't convert
                        pass

        except Exception as e:
            print(f"[ERROR] Parsing output for {language}: {e}")
            output_val = "Error parsing output"

        results.append(
            {
                "input": input_val,
                "expected": expected_output,
                "output": output_val,
                "passed": output_val == expected_output,
                "case_number": i,
            }
        )

    return results


# ------------------------
# ✅ Submit Test Cases
# ------------------------
def submit_test_cases(problem, code, language, user_id=None):
    print("submit_test_cases called__________________________________")
    test_cases_group = getattr(problem, "testcase_group", None)
    test_cases = test_cases_group.test_cases if test_cases_group else []

    inputs = [tc.get("input_data") for tc in test_cases]
    expected_outputs = [tc.get("output_data") for tc in test_cases]
    print(f"inputs:{inputs}")
    print(f"expected_outputs:{expected_outputs}")

    # Get starter code for the specific language
    starter_code = problem.starter_code.get_code(language, slug=problem.slug)
    func_name = get_function_name(
        starter_code, language, fallback=problem.slug.replace("-", "_")
    )

    results, times, passed_cases = [], [], 0

    for i, (input_val, expected_output) in enumerate(
        zip(inputs, expected_outputs), start=1
    ):
        try:
            input_dict = (
                json.loads(input_val) if isinstance(input_val, str) else input_val
            )
            args = [input_dict[key] for key in sorted(input_dict.keys(), key=int)]
        except Exception as e:
            args = []

        # Generate driver code based on language
        driver_code = generate_driver_code(language, func_name, args, problem.slug)

        if not driver_code:
            print(f"[ERROR] Unsupported language: {language}")
            results.append(
                {
                    "input": input_val,
                    "expected": expected_output,
                    "output": f"Unsupported language: {language}",
                    "passed": False,
                    "case_number": i,
                }
            )
            break

        if language == "java":
            # For Java, ensure class name is "Main" (required by Docker container)
            java_code = code.strip()
            # Replace "class Solution" with "class Main" if present
            java_code = re.sub(r"\bclass\s+Solution\b", "class Main", java_code)

            # Remove the last closing brace from user code and append driver code + closing brace
            user_code_without_last_brace = java_code.rstrip("}").rstrip()
            final_code = (
                user_code_without_last_brace + "\n" + textwrap.dedent(driver_code)
            )
        else:
            final_code = code.strip() + "\n\n" + textwrap.dedent(driver_code)

        start_time = time.time()
        result_output = execute_code(final_code, language=language, input_data="")
        time_taken = round(time.time() - start_time, 4)
        times.append(time_taken)

        try:
            output_lines = result_output.strip().splitlines()
            if not output_lines:
                output_val = "No output"
            else:
                output_line = output_lines[-1]

                # Parse output based on language
                if language == "python" or language == "c":
                    try:
                        output_val = json.loads(output_line)
                    except json.JSONDecodeError:
                        output_val = output_line
                else:
                    # For C++ and Java, the output is usually direct
                    output_val = output_line

                    # Try to convert to appropriate type if it's a number
                    try:
                        if "." in output_val:
                            output_val = float(output_val)
                        else:
                            output_val = int(output_val)
                    except (ValueError, TypeError):
                        # Keep as string if can't convert
                        pass

        except Exception as e:
            print(f"[ERROR] Parsing output for {language}: {e}")
            output_val = "Error parsing output"

        output_str = output_val.strip() if isinstance(output_val, str) else output_val
        expected_str = (
            expected_output.strip()
            if isinstance(expected_output, str)
            else expected_output
        )
        passed = output_str == expected_str

        results.append(
            {
                "input": input_val,
                "expected": expected_str,
                "output": output_str,
                "passed": passed,
                "case_number": i,
            }
        )

        if passed:
            passed_cases += 1
        else:
            break

    if user_id:
        log_submission_attempt(
            user_id=user_id,
            problem_id=str(problem.id),
            language=language,
            code=code,
            status="accepted" if passed_cases == len(test_cases) else "failed",
            time_taken=max(times) if times else 0,
        )

    return results, passed_cases, len(test_cases)


@login_required
def submit_comment(request, slug):
    if request.method == "POST":
        comment = request.POST.get("comment", "").strip()
        if comment:
            problem = get_object_or_404(Problem, slug=slug)
            save_comment(
                problem=problem,
                user_id=request.user.id,
                username=request.user.username,
                comment_text=comment,
            )
    return redirect("compile_with_problem", slug=slug)


from django.http import JsonResponse
from App.mongo import get_leaderboard_for_problem  # or leaderboard.py
from django.contrib.auth import get_user_model

User = get_user_model()


@login_required
def leaderboard_data(request, slug):
    from django.http import JsonResponse
    from App.mongo import get_leaderboard_for_problem
    from django.contrib.auth import get_user_model

    User = get_user_model()
    problem = get_object_or_404(Problem, slug=slug)
    user_id = str(request.user.id)

    print(f"🏆 Leaderboard request for problem: {problem.title} (ID: {problem.id})")
    print(f"👤 Current user ID: {user_id}")

    try:
        # Get all submissions
        records = get_leaderboard_for_problem(problem.id)
        print(f"📊 Raw records from MongoDB: {len(records)} records")
        print(f"🔍 Sample records: {records[:2] if records else 'No records'}")

        # Filter: Only accepted submissions
        accepted = [
            r for r in records if r.get("status") == "accepted" and "time_taken" in r
        ]
        print(f"✅ Accepted submissions: {len(accepted)}")

        # If no accepted submissions, let's check if there are ANY submissions for this problem
        if not accepted:
            print("⚠️ No accepted submissions found. Let's check all submissions...")
            from App.mongo import mongo_db

            all_submissions = list(
                mongo_db.submissions.find({"problem_id": str(problem.id)})
            )
            print(
                f"📋 Total submissions for problem {problem.id}: {len(all_submissions)}"
            )

            if all_submissions:
                print("📝 Sample submission structure:")
                for sub in all_submissions[:2]:
                    print(
                        f"   User: {sub.get('user_id')}, Submissions: {len(sub.get('submissions', []))}"
                    )
                    for attempt in sub.get("submissions", [])[:2]:
                        print(
                            f"     - Status: {attempt.get('status')}, Time: {attempt.get('time_taken')}"
                        )

        # Sort by best time
        accepted.sort(key=lambda x: x["time_taken"])

        leaderboard = []
        total = len(accepted)
        print(f"📈 Building leaderboard with {total} entries")

        for index, record in enumerate(accepted):
            uid = record.get("user_id")
            time = record.get("time_taken")
            user_obj = User.objects.filter(id=uid).first()
            username = user_obj.username if user_obj else "Anonymous"

            percentile = (
                round(((total - index - 1) / total) * 100, 2) if total > 0 else 0
            )

            leaderboard.append(
                {
                    "username": username,
                    "user_id": str(uid),
                    "time_taken": time,
                    "percentile": percentile,
                    "is_current_user": user_id == str(uid),
                }
            )
            print(f"   {index + 1}. {username}: {time}s ({percentile}%)")

        print(f"🎯 Final leaderboard: {len(leaderboard)} entries")
        return JsonResponse({"data": leaderboard, "success": True})

    except Exception as e:
        print(f"❌ Leaderboard error: {str(e)}")
        import traceback

        print(f"📍 Full traceback: {traceback.format_exc()}")
        return JsonResponse({"data": [], "success": False, "error": str(e)})


# Debug function to add test leaderboard data
@login_required
def add_test_leaderboard_data(request, slug):
    """Add some test data to the leaderboard for debugging"""
    from App.mongo import log_submission_attempt
    from django.http import JsonResponse

    problem = get_object_or_404(Problem, slug=slug)
    current_user_id = request.user.id

    print(f"🧪 Adding test data for problem: {problem.title} (ID: {problem.id})")

    # Add some fake submissions with different users and times
    test_data = [
        {
            "user_id": current_user_id,
            "time": 1.234,
            "code": "def solution(): return 'fast'",
        },
        {
            "user_id": str(int(current_user_id) + 100),
            "time": 2.456,
            "code": "def solution(): return 'medium'",
        },
        {
            "user_id": str(int(current_user_id) + 200),
            "time": 0.789,
            "code": "def solution(): return 'fastest'",
        },
    ]

    for i, data in enumerate(test_data):
        print(
            f"   Adding submission {i+1}: User {data['user_id']}, Time: {data['time']}s"
        )
        log_submission_attempt(
            user_id=str(data["user_id"]),
            problem_id=str(problem.id),
            language="python",
            code=data["code"],
            status="accepted",
            time_taken=data["time"],
        )

    return JsonResponse(
        {
            "message": f"Added {len(test_data)} test submissions for problem {problem.title}"
        }
    )


# ------------------------
# ✅ Problem Upload View
# ------------------------
@staff_member_required
def upload_problem(request):
    """View for uploading new problems - restricted to staff members"""
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Extract basic problem data
                title = request.POST.get("title", "").strip()
                slug = request.POST.get("slug", "").strip()
                difficulty = request.POST.get("difficulty", "").strip()
                statement = request.POST.get("statement", "").strip()
                tags = request.POST.get("tags", "").strip()
                constraints = request.POST.get("constraints", "").strip()
                hints = request.POST.get("hints", "").strip()
                time_limit = float(request.POST.get("time_limit", 2.0))
                memory_limit = int(request.POST.get("memory_limit", 128))
                is_active = request.POST.get("is_active") == "on"

                # Validate required fields
                if not all([title, slug, difficulty, statement]):
                    messages.error(
                        request,
                        "Please fill in all required fields (Title, Slug, Difficulty, Statement).",
                    )
                    return render(request, "problems/upload.html")

                # Check if slug already exists
                if Problem.objects.filter(slug=slug).exists():
                    messages.error(
                        request,
                        f'A problem with slug "{slug}" already exists. Please choose a different slug.',
                    )
                    return render(request, "problems/upload.html")

                # Create the problem
                problem = Problem.objects.create(
                    title=title,
                    slug=slug,
                    difficulty=difficulty,
                    statement=statement,
                    tags=tags,
                    constraints=constraints,
                    input_format="",  # You can add this to the form if needed
                    output_format="",  # You can add this to the form if needed
                )

                # Handle examples
                example_inputs = request.POST.getlist("example_input[]")
                example_outputs = request.POST.getlist("example_output[]")
                example_explanations = request.POST.getlist("example_explanation[]")

                examples_data = []
                for i, (inp, out) in enumerate(zip(example_inputs, example_outputs)):
                    if inp.strip() and out.strip():
                        example_data = {"input": inp.strip(), "output": out.strip()}
                        if (
                            i < len(example_explanations)
                            and example_explanations[i].strip()
                        ):
                            example_data["explanation"] = example_explanations[
                                i
                            ].strip()
                        examples_data.append(example_data)

                if examples_data:
                    from App.models import Example

                    Example.objects.create(problem=problem, examples=examples_data)

                # Handle test cases
                test_inputs = request.POST.getlist("test_input[]")
                test_outputs = request.POST.getlist("test_output[]")

                test_cases_data = []
                for inp, out in zip(test_inputs, test_outputs):
                    if inp.strip() and out.strip():
                        test_cases_data.append(
                            {"input_data": inp.strip(), "output_data": out.strip()}
                        )

                if test_cases_data:
                    from App.models import TestCase

                    TestCase.objects.create(problem=problem, test_cases=test_cases_data)

                # Handle starter code
                starter_languages = request.POST.getlist("starter_language[]")
                starter_codes = request.POST.getlist("starter_code[]")

                starter_code_data = {}
                for lang, code in zip(starter_languages, starter_codes):
                    if lang.strip() and code.strip():
                        starter_code_data[lang.strip()] = code.strip()

                if starter_code_data:
                    from App.models import StarterCode

                    starter_code_obj = StarterCode.objects.create(problem=problem)
                    # Set the codes for each language based on the model fields
                    for lang, code in starter_code_data.items():
                        if lang == "python":
                            starter_code_obj.base_code_python = code
                        elif lang == "cpp":
                            starter_code_obj.base_code_cpp = code
                        elif lang == "java":
                            starter_code_obj.base_code_java = code
                        elif lang == "c":
                            starter_code_obj.base_code_c = code
                    starter_code_obj.save()

                problem.save()

                messages.success(
                    request, f'Problem "{title}" has been uploaded successfully!'
                )
                return redirect("problems")  # Redirect to problems list

        except Exception as e:
            messages.error(request, f"Error uploading problem: {str(e)}")
            return render(request, "problems/upload.html")

    return render(request, "problems/upload.html")
