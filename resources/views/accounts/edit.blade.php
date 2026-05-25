<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">Edit Account</h2>
    </x-slot>

    <div class="py-8">
        <div class="max-w-xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="bg-white rounded-lg shadow p-6">
                <form method="POST" action="{{ route('accounts.update', $account) }}" class="space-y-5">
                    @csrf @method('PUT')

                    <div>
                        <x-input-label for="name" value="Account Name" />
                        <x-text-input id="name" name="name" type="text" class="mt-1 block w-full"
                                      value="{{ old('name', $account->name) }}" required autofocus />
                        <x-input-error :messages="$errors->get('name')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="type" value="Type" />
                        <select id="type" name="type"
                                class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                            @foreach (['checking' => 'Checking', 'savings' => 'Savings', 'credit_card' => 'Credit Card', 'cash' => 'Cash'] as $val => $label)
                                <option value="{{ $val }}" {{ old('type', $account->type) === $val ? 'selected' : '' }}>{{ $label }}</option>
                            @endforeach
                        </select>
                        <x-input-error :messages="$errors->get('type')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="currency" value="Currency" />
                        <x-text-input id="currency" name="currency" type="text" maxlength="3"
                                      class="mt-1 block w-full" value="{{ old('currency', $account->currency) }}" required />
                        <x-input-error :messages="$errors->get('currency')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="color" value="Card Color" />
                        <div class="mt-1 flex items-center gap-3">
                            <input id="color" name="color" type="color"
                                   class="h-9 w-16 border border-gray-300 rounded cursor-pointer"
                                   value="{{ old('color', $account->color ?? '#6366F1') }}" />
                        </div>
                        <x-input-error :messages="$errors->get('color')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="notes" value="Notes (optional)" />
                        <textarea id="notes" name="notes" rows="3"
                                  class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">{{ old('notes', $account->notes) }}</textarea>
                        <x-input-error :messages="$errors->get('notes')" class="mt-1" />
                    </div>

                    <div>
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input type="hidden" name="is_active" value="0">
                            <input id="is_active" name="is_active" type="checkbox" value="1"
                                   class="rounded border-gray-300 text-indigo-600"
                                   {{ old('is_active', $account->is_active) ? 'checked' : '' }}>
                            <span class="text-sm text-gray-700">Active account</span>
                        </label>
                    </div>

                    <div class="flex justify-end gap-3">
                        <a href="{{ route('accounts.index') }}"
                           class="px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-md hover:bg-gray-50">
                            Cancel
                        </a>
                        <x-primary-button>Save Changes</x-primary-button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</x-app-layout>
