<?php

namespace App\Http\Controllers;

use App\Models\Account;
use App\Models\Category;
use App\Models\Transaction;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\View\View;

class TransactionController extends Controller
{
    public function index(Request $request): View
    {
        $userId = auth()->id();

        $transactions = Transaction::with(['account', 'category'])
            ->where('user_id', $userId)
            ->when($request->account_id,  fn($q, $v) => $q->where('account_id', $v))
            ->when($request->category_id, fn($q, $v) => $q->where('category_id', $v))
            ->when($request->type,        fn($q, $v) => $q->where('type', $v))
            ->when($request->from,        fn($q, $v) => $q->whereDate('date', '>=', $v))
            ->when($request->to,          fn($q, $v) => $q->whereDate('date', '<=', $v))
            ->when($request->search,      fn($q, $v) => $q->where(
                fn($sq) => $sq->where('description', 'like', "%{$v}%")
                              ->orWhere('payee', 'like', "%{$v}%")
            ))
            ->orderByDesc('date')
            ->orderByDesc('id')
            ->paginate(25)
            ->withQueryString();

        $accounts   = $request->user()->accounts()->orderBy('name')->get();
        $categories = Category::forUser($userId)->orderBy('name')->get();

        return view('transactions.index', compact('transactions', 'accounts', 'categories'));
    }

    public function create(Request $request): View
    {
        $userId     = auth()->id();
        $accounts   = $request->user()->accounts()->where('is_active', true)->orderBy('name')->get();
        $categories = Category::forUser($userId)->orderBy('type')->orderBy('name')->get();
        $selectedAccountId = $request->account_id;

        return view('transactions.create', compact('accounts', 'categories', 'selectedAccountId'));
    }

    public function store(Request $request): RedirectResponse
    {
        $validated = $request->validate([
            'account_id'  => 'required|exists:accounts,id',
            'category_id' => 'nullable|exists:categories,id',
            'amount'      => 'required|numeric|min:0.01',
            'type'        => 'required|in:income,expense',
            'date'        => 'required|date',
            'description' => 'nullable|string|max:255',
            'payee'       => 'nullable|string|max:100',
            'notes'       => 'nullable|string|max:1000',
        ]);

        $account = Account::findOrFail($validated['account_id']);
        abort_if($account->user_id !== auth()->id(), 403);

        $validated['user_id'] = auth()->id();
        Transaction::create($validated);

        $this->recalculateBalance($account);

        return redirect()->route('transactions.index')->with('success', 'Transaction added.');
    }

    public function edit(Transaction $transaction): View
    {
        abort_if($transaction->user_id !== auth()->id(), 403);

        $userId     = auth()->id();
        $accounts   = auth()->user()->accounts()->where('is_active', true)->orderBy('name')->get();
        $categories = Category::forUser($userId)->orderBy('type')->orderBy('name')->get();

        return view('transactions.edit', compact('transaction', 'accounts', 'categories'));
    }

    public function update(Request $request, Transaction $transaction): RedirectResponse
    {
        abort_if($transaction->user_id !== auth()->id(), 403);

        $validated = $request->validate([
            'account_id'  => 'required|exists:accounts,id',
            'category_id' => 'nullable|exists:categories,id',
            'amount'      => 'required|numeric|min:0.01',
            'type'        => 'required|in:income,expense',
            'date'        => 'required|date',
            'description' => 'nullable|string|max:255',
            'payee'       => 'nullable|string|max:100',
            'notes'       => 'nullable|string|max:1000',
        ]);

        $oldAccount = $transaction->account;
        $newAccount = Account::findOrFail($validated['account_id']);
        abort_if($newAccount->user_id !== auth()->id(), 403);

        $transaction->update($validated);

        $this->recalculateBalance($oldAccount);
        if ($oldAccount->id !== $newAccount->id) {
            $this->recalculateBalance($newAccount);
        }

        return redirect()->route('transactions.index')->with('success', 'Transaction updated.');
    }

    public function destroy(Transaction $transaction): RedirectResponse
    {
        abort_if($transaction->user_id !== auth()->id(), 403);

        $account = $transaction->account;
        $transaction->delete();
        $this->recalculateBalance($account);

        return redirect()->route('transactions.index')->with('success', 'Transaction deleted.');
    }

    private function recalculateBalance(Account $account): void
    {
        $account->balance = Transaction::where('account_id', $account->id)
            ->selectRaw('SUM(CASE WHEN type = "income" THEN amount ELSE -amount END) as net')
            ->value('net') ?? 0;
        $account->save();
    }
}
