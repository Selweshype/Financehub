<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">Add Account</h2>
    </x-slot>

    <div class="py-8">
        <div class="max-w-xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="bg-white rounded-lg shadow p-6">
                <form method="POST" action="{{ route('accounts.store') }}" class="space-y-5">
                    @csrf

                    <div>
                        <x-input-label for="name" value="Account Name" />
                        <x-text-input id="name" name="name" type="text" class="mt-1 block w-full"
                                      value="{{ old('name') }}" required autofocus />
                        <x-input-error :messages="$errors->get('name')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="type" value="Type" />
                        <select id="type" name="type"
                                class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                            @foreach (['checking' => 'Checking', 'savings' => 'Savings', 'credit_card' => 'Credit Card', 'cash' => 'Cash'] as $val => $label)
                                <option value="{{ $val }}" {{ old('type') === $val ? 'selected' : '' }}>{{ $label }}</option>
                            @endforeach
                        </select>
                        <x-input-error :messages="$errors->get('type')" class="mt-1" />
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <x-input-label for="balance" value="Opening Balance" />
                            <x-text-input id="balance" name="balance" type="number" step="0.01"
                                          class="mt-1 block w-full" value="{{ old('balance', '0.00') }}" required />
                            <x-input-error :messages="$errors->get('balance')" class="mt-1" />
                        </div>
                        <div>
                            <x-input-label for="currency" value="Currency" />
                            <x-text-input id="currency" name="currency" type="text" maxlength="3"
                                          class="mt-1 block w-full" value="{{ old('currency', 'EUR') }}" required />
                            <x-input-error :messages="$errors->get('currency')" class="mt-1" />
                        </div>
                    </div>

                    <div>
                        <x-input-label for="color" value="Card Color (optional)" />
                        <div class="mt-1 flex items-center gap-3">
                            <input id="color" name="color" type="color"
                                   class="h-9 w-16 border border-gray-300 rounded cursor-pointer"
                                   value="{{ old('color', '#6366F1') }}" />
                            <span class="text-sm text-gray-500">Pick a color for this account card</span>
                        </div>
                        <x-input-error :messages="$errors->get('color')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="notes" value="Notes (optional)" />
                        <textarea id="notes" name="notes" rows="3"
                                  class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">{{ old('notes') }}</textarea>
                        <x-input-error :messages="$errors->get('notes')" class="mt-1" />
                    </div>

                    <div class="flex justify-end gap-3">
                        <a href="{{ route('accounts.index') }}"
                           class="px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-md hover:bg-gray-50">
                            Cancel
                        </a>
                        <x-primary-button>Create Account</x-primary-button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</x-app-layout>
