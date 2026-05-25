<?php

namespace App\Http\Controllers;

use App\Models\Budget;
use App\Models\Category;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\View\View;

class BudgetController extends Controller
{
    public function index(Request $request): View
    {
        $month = (int) $request->get('month', now()->month);
        $year  = (int) $request->get('year', now()->year);

        $budgets = $request->user()->budgets()
            ->with('category')
            ->where('month', $month)
            ->where('year', $year)
            ->get()
            ->map(fn($budget) => [
                'budget'     => $budget,
                'spent'      => $budget->spent,
                'percentage' => $budget->percentage,
            ]);

        $prevMonth = now()->setMonth($month)->setYear($year)->subMonth();
        $nextMonth = now()->setMonth($month)->setYear($year)->addMonth();

        return view('budgets.index', compact('budgets', 'month', 'year', 'prevMonth', 'nextMonth'));
    }

    public function create(): View
    {
        $userId     = auth()->id();
        $categories = Category::forUser($userId)
            ->where('type', 'expense')
            ->orderBy('name')
            ->get();

        return view('budgets.create', compact('categories'));
    }

    public function store(Request $request): RedirectResponse
    {
        $validated = $request->validate([
            'category_id' => [
                'required',
                'exists:categories,id',
                function ($attribute, $value, $fail) use ($request) {
                    $exists = Budget::where('user_id', auth()->id())
                        ->where('category_id', $value)
                        ->where('month', $request->month)
                        ->where('year', $request->year)
                        ->exists();
                    if ($exists) {
                        $fail('A budget for this category and month already exists.');
                    }
                },
            ],
            'amount' => 'required|numeric|min:1',
            'month'  => 'required|integer|between:1,12',
            'year'   => 'required|integer|min:2000|max:2100',
        ]);

        $validated['user_id'] = auth()->id();
        Budget::create($validated);

        return redirect()->route('budgets.index', [
            'month' => $validated['month'],
            'year'  => $validated['year'],
        ])->with('success', 'Budget created.');
    }

    public function destroy(Budget $budget): RedirectResponse
    {
        abort_if($budget->user_id !== auth()->id(), 403);

        $month = $budget->month;
        $year  = $budget->year;
        $budget->delete();

        return redirect()->route('budgets.index', compact('month', 'year'))
            ->with('success', 'Budget deleted.');
    }
}
