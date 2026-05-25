<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">
            {{ __('Dashboard') }}
        </h2>
    </x-slot>

    <div class="py-8">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">

            {{-- Summary Cards --}}
            <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                <div class="bg-white rounded-lg shadow p-6">
                    <p class="text-sm font-medium text-gray-500">Total Balance</p>
                    <p class="mt-1 text-2xl font-bold text-gray-900">€{{ number_format($totalBalance, 2) }}</p>
                </div>
                <div class="bg-white rounded-lg shadow p-6">
                    <p class="text-sm font-medium text-gray-500">Income This Month</p>
                    <p class="mt-1 text-2xl font-bold text-green-600">€{{ number_format($monthlyIncome, 2) }}</p>
                </div>
                <div class="bg-white rounded-lg shadow p-6">
                    <p class="text-sm font-medium text-gray-500">Expenses This Month</p>
                    <p class="mt-1 text-2xl font-bold text-red-600">€{{ number_format($monthlyExpenses, 2) }}</p>
                </div>
                <div class="bg-white rounded-lg shadow p-6">
                    <p class="text-sm font-medium text-gray-500">Net Savings</p>
                    @php $net = $monthlyIncome - $monthlyExpenses; @endphp
                    <p class="mt-1 text-2xl font-bold {{ $net >= 0 ? 'text-green-600' : 'text-red-600' }}">
                        €{{ number_format($net, 2) }}
                    </p>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

                {{-- Recent Transactions --}}
                <div class="lg:col-span-2 bg-white rounded-lg shadow">
                    <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                        <h3 class="text-lg font-semibold text-gray-800">Recent Transactions</h3>
                        <a href="{{ route('transactions.index') }}" class="text-sm text-indigo-600 hover:underline">View all</a>
                    </div>
                    @if ($recentTransactions->isEmpty())
                        <p class="px-6 py-8 text-center text-gray-500 text-sm">No transactions yet.
                            <a href="{{ route('transactions.create') }}" class="text-indigo-600 hover:underline">Add one</a>.
                        </p>
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
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-gray-100">
                                    @foreach ($recentTransactions as $tx)
                                        <tr class="hover:bg-gray-50">
                                            <td class="px-6 py-3 whitespace-nowrap text-gray-500">{{ $tx->date->format('d M') }}</td>
                                            <td class="px-6 py-3">
                                                <span class="font-medium text-gray-800">{{ $tx->description ?: $tx->payee ?: '—' }}</span>
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
                                        </tr>
                                    @endforeach
                                </tbody>
                            </table>
                        </div>
                    @endif
                </div>

                {{-- Budget Status --}}
                <div class="bg-white rounded-lg shadow">
                    <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                        <h3 class="text-lg font-semibold text-gray-800">Budget Status</h3>
                        <a href="{{ route('budgets.index') }}" class="text-sm text-indigo-600 hover:underline">Manage</a>
                    </div>
                    @if ($budgetStatus->isEmpty())
                        <p class="px-6 py-8 text-center text-gray-500 text-sm">No budgets set.
                            <a href="{{ route('budgets.create') }}" class="text-indigo-600 hover:underline">Create one</a>.
                        </p>
                    @else
                        <div class="px-6 py-4 space-y-4">
                            @foreach ($budgetStatus as $item)
                                @php
                                    $pct = $item['percentage'];
                                    $color = $pct >= 100 ? 'bg-red-500' : ($pct >= 75 ? 'bg-amber-400' : 'bg-green-500');
                                @endphp
                                <div>
                                    <div class="flex justify-between items-center mb-1">
                                        <span class="text-sm font-medium text-gray-700">
                                            {{ $item['budget']->category->icon }} {{ $item['budget']->category->name }}
                                        </span>
                                        <span class="text-xs text-gray-500">
                                            €{{ number_format($item['spent'], 0) }} / €{{ number_format($item['budget']->amount, 0) }}
                                        </span>
                                    </div>
                                    <div class="w-full bg-gray-200 rounded-full h-2">
                                        <div class="{{ $color }} h-2 rounded-full transition-all"
                                             style="width: {{ $pct }}%"></div>
                                    </div>
                                </div>
                            @endforeach
                        </div>
                    @endif
                </div>

            </div>
        </div>
    </div>
</x-app-layout>
