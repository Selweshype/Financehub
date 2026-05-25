<?php

namespace App\Http\Controllers;

use App\Models\Transaction;
use Illuminate\Http\Request;
use Illuminate\View\View;

class DashboardController extends Controller
{
    public function index(Request $request): View
    {
        $user = $request->user();

        $totalBalance = $user->accounts()->where('is_active', true)->sum('balance');

        $monthlyIncome = Transaction::where('user_id', $user->id)
            ->where('type', 'income')
            ->whereMonth('date', now()->month)
            ->whereYear('date', now()->year)
            ->sum('amount');

        $monthlyExpenses = Transaction::where('user_id', $user->id)
            ->where('type', 'expense')
            ->whereMonth('date', now()->month)
            ->whereYear('date', now()->year)
            ->sum('amount');

        $recentTransactions = Transaction::with(['account', 'category'])
            ->where('user_id', $user->id)
            ->orderByDesc('date')
            ->orderByDesc('id')
            ->limit(10)
            ->get();

        $budgetStatus = $user->budgets()
            ->with('category')
            ->where('month', now()->month)
            ->where('year', now()->year)
            ->get()
            ->map(fn($budget) => [
                'budget'     => $budget,
                'spent'      => $budget->spent,
                'percentage' => $budget->percentage,
            ]);

        return view('dashboard', compact(
            'totalBalance',
            'monthlyIncome',
            'monthlyExpenses',
            'recentTransactions',
            'budgetStatus',
        ));
    }
}
