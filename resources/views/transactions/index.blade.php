<x-app-layout>
    <x-slot name="header">
        <div class="flex justify-between items-center">
            <h2 class="font-semibold text-xl text-gray-800 leading-tight">Transactions</h2>
            <a href="{{ route('transactions.create') }}"
               class="inline-flex items-center px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700">
                + Add Transaction
            </a>
        </div>
    </x-slot>

    <div class="py-8">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-4">

            @if (session('success'))
                <div class="px-4 py-3 bg-green-100 text-green-800 rounded-md text-sm">{{ session('success') }}</div>
            @endif

            {{-- Filters --}}
            <div class="bg-white rounded-lg shadow p-4">
                <form method="GET" action="{{ route('transactions.index') }}"
                      class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 items-end">

                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">Account</label>
                        <select name="account_id"
                                class="block w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500">
                            <option value="">All accounts</option>
                            @foreach ($accounts as $account)
                                <option value="{{ $account->id }}" {{ request('account_id') == $account->id ? 'selected' : '' }}>
                                    {{ $account->name }}
                                </option>
                            @endforeach
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">Category</label>
                        <select name="category_id"
                                class="block w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500">
                            <option value="">All categories</option>
                            @foreach ($categories as $cat)
                                <option value="{{ $cat->id }}" {{ request('category_id') == $cat->id ? 'selected' : '' }}>
                                    {{ $cat->icon }} {{ $cat->name }}
                                </option>
                            @endforeach
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">Type</label>
                        <select name="type"
                                class="block w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500">
                            <option value="">All types</option>
                            <option value="income"  {{ request('type') === 'income'  ? 'selected' : '' }}>Income</option>
                            <option value="expense" {{ request('type') === 'expense' ? 'selected' : '' }}>Expense</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">From</label>
                        <input type="date" name="from" value="{{ request('from') }}"
                               class="block w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500">
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">To</label>
                        <input type="date" name="to" value="{{ request('to') }}"
                               class="block w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500">
                    </div>

                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">Search</label>
                        <div class="flex gap-2">
                            <input type="text" name="search" value="{{ request('search') }}"
                                   placeholder="Description / Payee"
                                   class="block w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500">
                            <button type="submit"
                                    class="px-3 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 whitespace-nowrap">
                                Filter
                            </button>
                        </div>
                    </div>

                </form>
                @if (request()->hasAny(['account_id', 'category_id', 'type', 'from', 'to', 'search']))
                    <div class="mt-2">
                        <a href="{{ route('transactions.index') }}" class="text-sm text-gray-500 hover:underline">Clear filters</a>
                    </div>
                @endif
            </div>

            {{-- Table --}}
            <div class="bg-white rounded-lg shadow overflow-hidden">
                @if ($transactions->isEmpty())
                    <p class="px-6 py-10 text-center text-gray-500">No transactions found.</p>
                @else
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead class="bg-gray-50 text-gray-500 uppercase text-xs">
                                <tr>
                                    <th class="px-6 py-3 text-left">Date</th>
                                    <th class="px-6 py-3 text-left">Description</th>
                                    <th class="px-6 py-3 text-left">Category</th>
                                    <th class="px-6 py-3 text-left">Account</th>
                                    <th class="px-6 py-3 text-right">Amount</th>
                                    <th class="px-6 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100">
                                @foreach ($transactions as $tx)
                                    <tr class="hover:bg-gray-50">
                                        <td class="px-6 py-3 whitespace-nowrap text-gray-500">{{ $tx->date->format('d M Y') }}</td>
                                        <td class="px-6 py-3">
                                            <span class="font-medium text-gray-800">{{ $tx->description ?: '—' }}</span>
                                            @if ($tx->payee)
                                                <span class="block text-xs text-gray-400">{{ $tx->payee }}</span>
                                            @endif
                                        </td>
                                        <td class="px-6 py-3">
                                            @if ($tx->category)
                                                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium text-white"
                                                      style="background-color: {{ $tx->category->color ?? '#6B7280' }}">
                                                    {{ $tx->category->icon }} {{ $tx->category->name }}
                                                </span>
                                            @else
                                                <span class="text-gray-400">—</span>
                                            @endif
                                        </td>
                                        <td class="px-6 py-3 text-gray-600">{{ $tx->account->name }}</td>
                                        <td class="px-6 py-3 text-right font-semibold {{ $tx->type === 'income' ? 'text-green-600' : 'text-red-600' }}">
                                            {{ $tx->type === 'income' ? '+' : '−' }}€{{ number_format($tx->amount, 2) }}
                                        </td>
                                        <td class="px-6 py-3 text-right whitespace-nowrap">
                                            <a href="{{ route('transactions.edit', $tx) }}"
                                               class="text-indigo-600 hover:underline text-xs mr-3">Edit</a>
                                            <form action="{{ route('transactions.destroy', $tx) }}" method="POST"
                                                  class="inline" onsubmit="return confirm('Delete this transaction?')">
                                                @csrf @method('DELETE')
                                                <button type="submit" class="text-red-600 hover:underline text-xs">Delete</button>
                                            </form>
                                        </td>
                                    </tr>
                                @endforeach
                            </tbody>
                        </table>
                    </div>
                    <div class="px-6 py-4 border-t border-gray-100">
                        {{ $transactions->links() }}
                    </div>
                @endif
            </div>

        </div>
    </div>
</x-app-layout>
