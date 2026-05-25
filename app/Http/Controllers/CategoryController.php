<?php

namespace App\Http\Controllers;

use App\Models\Category;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\View\View;

class CategoryController extends Controller
{
    public function index(Request $request): View
    {
        $categories = Category::forUser($request->user()->id)
            ->orderBy('type')
            ->orderBy('name')
            ->get()
            ->groupBy('type');

        return view('categories.index', compact('categories'));
    }

    public function store(Request $request): RedirectResponse
    {
        $validated = $request->validate([
            'name'  => 'required|string|max:100',
            'type'  => 'required|in:income,expense',
            'icon'  => 'nullable|string|max:10',
            'color' => 'nullable|regex:/^#[0-9A-Fa-f]{6}$/',
        ]);

        $validated['user_id'] = $request->user()->id;
        Category::create($validated);

        return redirect()->route('categories.index')->with('success', 'Category created.');
    }

    public function destroy(Category $category): RedirectResponse
    {
        abort_if($category->user_id !== auth()->id(), 403);
        abort_if($category->is_default, 403);

        $category->delete();

        return redirect()->route('categories.index')->with('success', 'Category deleted.');
    }
}
