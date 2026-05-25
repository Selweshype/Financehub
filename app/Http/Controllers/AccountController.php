<?php

namespace App\Http\Controllers;

use App\Models\Account;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\View\View;

class AccountController extends Controller
{
    public function index(Request $request): View
    {
        $accounts = $request->user()->accounts()->orderBy('name')->get();

        return view('accounts.index', compact('accounts'));
    }

    public function create(): View
    {
        return view('accounts.create');
    }

    public function store(Request $request): RedirectResponse
    {
        $validated = $request->validate([
            'name'     => 'required|string|max:100',
            'type'     => 'required|in:checking,savings,credit_card,cash',
            'balance'  => 'required|numeric',
            'currency' => 'required|size:3',
            'color'    => 'nullable|regex:/^#[0-9A-Fa-f]{6}$/',
            'notes'    => 'nullable|string|max:500',
        ]);

        $request->user()->accounts()->create($validated);

        return redirect()->route('accounts.index')->with('success', 'Account created.');
    }

    public function edit(Account $account): View
    {
        abort_if($account->user_id !== auth()->id(), 403);

        return view('accounts.edit', compact('account'));
    }

    public function update(Request $request, Account $account): RedirectResponse
    {
        abort_if($account->user_id !== auth()->id(), 403);

        $validated = $request->validate([
            'name'      => 'required|string|max:100',
            'type'      => 'required|in:checking,savings,credit_card,cash',
            'currency'  => 'required|size:3',
            'color'     => 'nullable|regex:/^#[0-9A-Fa-f]{6}$/',
            'notes'     => 'nullable|string|max:500',
            'is_active' => 'boolean',
        ]);

        $account->update($validated);

        return redirect()->route('accounts.index')->with('success', 'Account updated.');
    }

    public function destroy(Account $account): RedirectResponse
    {
        abort_if($account->user_id !== auth()->id(), 403);

        $account->delete();

        return redirect()->route('accounts.index')->with('success', 'Account deleted.');
    }
}
