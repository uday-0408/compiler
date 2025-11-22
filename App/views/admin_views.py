import os
import json
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.text import slugify
from django.db import transaction
from App.models import Problem, Category, StarterCode, Example, TestCase


def generate_unique_slug(model, base_slug):
    """Generate a unique slug for the given model"""
    slug = base_slug
    counter = 1
    while model.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def admin_problem_insert(request):
    """
    Admin panel for inserting new problems into the database.
    Requires password authentication from environment variable.
    """

    # Check if user is already authenticated for this session
    authenticated = request.session.get("admin_authenticated", False)

    if request.method == "POST":
        action = request.POST.get("action")

        # Handle authentication
        if action == "authenticate":
            password = request.POST.get("password", "")
            admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

            if password == admin_password:
                request.session["admin_authenticated"] = True
                messages.success(
                    request, "Authentication successful! Welcome to the admin panel."
                )
                return redirect("admin-problem-insert")
            else:
                messages.error(request, "Invalid password. Access denied.")
                return render(
                    request,
                    "admin_problem_insert.html",
                    {
                        "authenticated": False,
                        "error": "Invalid password. Please try again.",
                    },
                )

        # Handle problem insertion
        elif action == "insert" and authenticated:
            try:
                with transaction.atomic():
                    # Basic information
                    title = request.POST.get("title", "").strip()
                    difficulty = request.POST.get("difficulty", "Easy")
                    tags = request.POST.get("tags", "").strip()

                    if not title:
                        raise ValueError("Problem title is required")

                    # Generate unique slug
                    base_slug = slugify(title)
                    slug = generate_unique_slug(Problem, base_slug)

                    # Problem statement
                    statement = request.POST.get("statement", "").strip()
                    input_format = request.POST.get("input_format", "").strip()
                    output_format = request.POST.get("output_format", "").strip()
                    constraints = request.POST.get("constraints", "").strip()

                    if not statement:
                        raise ValueError("Problem statement is required")

                    # Get or create category (using difficulty as category for now)
                    category, created = Category.objects.get_or_create(
                        name=difficulty,
                        defaults={"description": f"{difficulty} level problems"},
                    )

                    # Create the problem
                    problem = Problem.objects.create(
                        title=title,
                        slug=slug,
                        statement=statement,
                        input_format=input_format,
                        output_format=output_format,
                        constraints=constraints,
                        difficulty=difficulty,
                        tags=tags,
                    )

                    # Add the category after creation (using the many-to-many relationship)
                    problem.categories.add(category)

                    # Create starter code
                    starter_code = StarterCode.objects.create(
                        problem=problem,
                        base_code_python=request.POST.get("python_code", "").strip(),
                        base_code_java=request.POST.get("java_code", "").strip(),
                        base_code_cpp=request.POST.get("cpp_code", "").strip(),
                        base_code_c=request.POST.get("c_code", "").strip(),
                    )

                    # Create examples
                    example_inputs = request.POST.getlist("example_input[]")
                    example_outputs = request.POST.getlist("example_output[]")

                    examples_data = []
                    for i, (input_data, output_data) in enumerate(
                        zip(example_inputs, example_outputs)
                    ):
                        if input_data.strip() and output_data.strip():
                            try:
                                # Validate JSON format
                                json.loads(input_data)
                                examples_data.append(
                                    {
                                        "input": input_data.strip(),
                                        "output": output_data.strip(),
                                    }
                                )
                            except json.JSONDecodeError:
                                raise ValueError(
                                    f"Example {i+1} input must be valid JSON"
                                )

                    if examples_data:
                        # Create examples group
                        examples_group = Example.objects.create(
                            problem=problem, examples=examples_data
                        )

                    # Create test cases
                    testcase_inputs = request.POST.getlist("testcase_input[]")
                    testcase_outputs = request.POST.getlist("testcase_output[]")

                    test_cases_data = []
                    for i, (input_data, output_data) in enumerate(
                        zip(testcase_inputs, testcase_outputs)
                    ):
                        if input_data.strip() and output_data.strip():
                            try:
                                # Validate JSON format
                                json.loads(input_data)
                                test_cases_data.append(
                                    {
                                        "input_data": input_data.strip(),
                                        "output_data": output_data.strip(),
                                    }
                                )
                            except json.JSONDecodeError:
                                raise ValueError(
                                    f"Test case {i+1} input must be valid JSON"
                                )

                    if test_cases_data:
                        # Create test cases group
                        testcase_group = TestCase.objects.create(
                            problem=problem, test_cases=test_cases_data
                        )

                    messages.success(
                        request,
                        f'Problem "{title}" has been successfully created with slug "{slug}"!',
                    )

                    # Log the creation
                    print(f"✅ Problem created successfully:")
                    print(f"📝 Title: {title}")
                    print(f"🔗 Slug: {slug}")
                    print(f"📊 Difficulty: {difficulty}")
                    print(f"📋 Examples: {len(examples_data)}")
                    print(f"🧪 Test Cases: {len(test_cases_data)}")

                    # Clear form data after successful creation
                    return redirect("admin-problem-insert")

            except ValueError as e:
                messages.error(request, f"Validation Error: {str(e)}")
                print(f"❌ Validation Error: {str(e)}")

            except Exception as e:
                messages.error(request, f"Error creating problem: {str(e)}")
                print(f"❌ Error creating problem: {str(e)}")
                import traceback

                traceback.print_exc()

    return render(
        request, "admin_problem_insert.html", {"authenticated": authenticated}
    )


def admin_logout(request):
    """Logout from admin session"""
    request.session.pop("admin_authenticated", None)
    messages.info(request, "You have been logged out from the admin panel.")
    return redirect("admin-problem-insert")
