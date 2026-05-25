<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">Add Transaction</h2>
    </x-slot>

    <div class="py-8">
        <div class="max-w-xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="bg-white rounded-lg shadow p-6">
                <form method="POST" action="{{ route('transactions.store') }}" class="space-y-5">
                    @csrf

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <x-input-label for="type" value="Type" />
                            <div class="mt-1 flex rounded-md overflow-hidden border border-gray-300">
                                <label class="flex-1 text-center cursor-pointer">
                                    <input type="radio" name="type" value="expense" class="sr-only peer"
                                           {{ old('type', 'expense') === 'expense' ? 'checked' : '' }}>
                                    <span class="block py-2 text-sm font-medium text-gray-700 peer-checked:bg-red-500 peer-checked:text-white">
                                        Expense
                                    </span>
                                </label>
                                <label class="flex-1 text-center cursor-pointer">
                                    <input type="radio" name="type" value="income" class="sr-only peer"
                                           {{ old('type') === 'income' ? 'checked' : '' }}>
                                    <span class="block py-2 text-sm font-medium text-gray-700 peer-checked:bg-green-500 peer-checked:text-white">
                                        Income
                                    </span>
                                </label>
                            </div>
                            <x-input-error :messages="$errors->get('type')" class="mt-1" />
                        </div>

                        <div>
                            <x-input-label for="amount" value="Amount" />
                            <x-text-input id="amount" name="amount" type="number" step="0.01" min="0.01"
                                          class="mt-1 block w-full" value="{{ old('amount') }}" required />
                            <x-input-error :messages="$errors->get('amount')" class="mt-1" />
                        </div>
                    </div>

                    <div>
                        <x-input-label for="date" value="Date" />
                        <x-text-input id="date" name="date" type="date" class="mt-1 block w-full"
                                      value="{{ old('date', now()->format('Y-m-d')) }}" required />
                        <x-input-error :messages="$errors->get('date')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="account_id" value="Account" />
                        <select id="account_id" name="account_id"
                                class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                            <option value="">Select account...</option>
                            @foreach ($accounts as $account)
                                <option value="{{ $account->id }}"
                                        {{ old('account_id', $selectedAccountId) == $account->id ? 'selected' : '' }}>
                                    {{ $account->name }} ({{ $account->currency }} {{ number_format($account->balance, 2) }})
                                </option>
                            @endforeach
                        </select>
                        <x-input-error :messages="$errors->get('account_id')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="category_id" value="Category (optional)" />
                        <select id="category_id" name="category_id"
                                class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                            <option value="">No category</option>
                            <optgroup label="Expense">
                                @foreach ($categories->where('type', 'expense') as $cat)
                                    <option value="{{ $cat->id }}" {{ old('category_id') == $cat->id ? 'selected' : '' }}>
                                        {{ $cat->icon }} {{ $cat->name }}
                                    </option>
                                @endforeach
                            </optgroup>
                            <optgroup label="Income">
                                @foreach ($categories->where('type', 'income') as $cat)
                                    <option value="{{ $cat->id }}" {{ old('category_id') == $cat->id ? 'selected' : '' }}>
                                        {{ $cat->icon }} {{ $cat->name }}
                                    </option>
                                @endforeach
                            </optgroup>
                        </select>
                        <x-input-error :messages="$errors->get('category_id')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="description" value="Description (optional)" />
                        <x-text-input id="description" name="description" type="text"
                                      class="mt-1 block w-full" value="{{ old('description') }}" />
                        <x-input-error :messages="$errors->get('description')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="payee" value="Payee / Merchant (optional)" />
                        <x-text-input id="payee" name="payee" type="text"
                                      class="mt-1 block w-full" value="{{ old('payee') }}" />
                        <x-input-error :messages="$errors->get('payee')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="notes" value="Notes (optional)" />
                        <textarea id="notes" name="notes" rows="2"
                                  class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">{{ old('notes') }}</textarea>
                        <x-input-error :messages="$errors->get('notes')" class="mt-1" />
                    </div>

                    <div class="flex justify-end gap-3">
                        <a href="{{ route('transactions.index') }}"
                           class="px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-md hover:bg-gray-50">
                            Cancel
                        </a>
                        <x-primary-button>Add Transaction</x-primary-button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</x-app-layout>
