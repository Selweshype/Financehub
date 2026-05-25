<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">Add Budget</h2>
    </x-slot>

    <div class="py-8">
        <div class="max-w-xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="bg-white rounded-lg shadow p-6">
                <form method="POST" action="{{ route('budgets.store') }}" class="space-y-5">
                    @csrf

                    <div>
                        <x-input-label for="category_id" value="Category" />
                        <select id="category_id" name="category_id"
                                class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                            <option value="">Select a category...</option>
                            @foreach ($categories as $cat)
                                <option value="{{ $cat->id }}" {{ old('category_id') == $cat->id ? 'selected' : '' }}>
                                    {{ $cat->icon }} {{ $cat->name }}
                                </option>
                            @endforeach
                        </select>
                        <x-input-error :messages="$errors->get('category_id')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="amount" value="Monthly Limit (€)" />
                        <x-text-input id="amount" name="amount" type="number" step="1" min="1"
                                      class="mt-1 block w-full" value="{{ old('amount') }}" required />
                        <x-input-error :messages="$errors->get('amount')" class="mt-1" />
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <x-input-label for="month" value="Month" />
                            <select id="month" name="month"
                                    class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                                @foreach (range(1, 12) as $m)
                                    <option value="{{ $m }}" {{ old('month', now()->month) == $m ? 'selected' : '' }}>
                                        {{ \Carbon\Carbon::createFromDate(null, $m, 1)->format('F') }}
                                    </option>
                                @endforeach
                            </select>
                            <x-input-error :messages="$errors->get('month')" class="mt-1" />
                        </div>

                        <div>
                            <x-input-label for="year" value="Year" />
                            <x-text-input id="year" name="year" type="number" min="2000" max="2100"
                                          class="mt-1 block w-full" value="{{ old('year', now()->year) }}" required />
                            <x-input-error :messages="$errors->get('year')" class="mt-1" />
                        </div>
                    </div>

                    <div class="flex justify-end gap-3">
                        <a href="{{ route('budgets.index') }}"
                           class="px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-md hover:bg-gray-50">
                            Cancel
                        </a>
                        <x-primary-button>Create Budget</x-primary-button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</x-app-layout>
