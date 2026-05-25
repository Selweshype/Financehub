<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">Categories</h2>
    </x-slot>

    <div class="py-8">
        <div class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">

            @if (session('success'))
                <div class="px-4 py-3 bg-green-100 text-green-800 rounded-md text-sm">{{ session('success') }}</div>
            @endif

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">

                @foreach (['expense' => 'Expense', 'income' => 'Income'] as $type => $label)
                    <div class="bg-white rounded-lg shadow overflow-hidden">
                        <div class="px-6 py-4 border-b border-gray-200 {{ $type === 'expense' ? 'bg-red-50' : 'bg-green-50' }}">
                            <h3 class="font-semibold text-gray-800">{{ $label }} Categories</h3>
                        </div>
                        <ul class="divide-y divide-gray-100">
                            @forelse ($categories->get($type, collect()) as $cat)
                                <li class="flex items-center justify-between px-6 py-3">
                                    <div class="flex items-center gap-3">
                                        <span class="text-lg">{{ $cat->icon }}</span>
                                        <span class="text-sm font-medium text-gray-800">{{ $cat->name }}</span>
                                        @if ($cat->color)
                                            <span class="inline-block h-3 w-3 rounded-full border border-gray-200"
                                                  style="background-color: {{ $cat->color }}"></span>
                                        @endif
                                        @if ($cat->is_default)
                                            <span class="text-xs text-gray-400">default</span>
                                        @endif
                                    </div>
                                    @unless ($cat->is_default)
                                        <form action="{{ route('categories.destroy', $cat) }}" method="POST"
                                              onsubmit="return confirm('Delete this category?')">
                                            @csrf @method('DELETE')
                                            <button type="submit" class="text-red-400 hover:text-red-600 text-xs">Delete</button>
                                        </form>
                                    @endunless
                                </li>
                            @empty
                                <li class="px-6 py-4 text-sm text-gray-400">No {{ strtolower($label) }} categories.</li>
                            @endforelse
                        </ul>
                    </div>
                @endforeach

            </div>

            {{-- Add custom category --}}
            <div class="bg-white rounded-lg shadow p-6">
                <h3 class="font-semibold text-gray-800 mb-4">Add Custom Category</h3>
                <form method="POST" action="{{ route('categories.store') }}"
                      class="grid grid-cols-2 sm:grid-cols-4 gap-3 items-end">
                    @csrf

                    <div>
                        <x-input-label for="name" value="Name" />
                        <x-text-input id="name" name="name" type="text" class="mt-1 block w-full"
                                      value="{{ old('name') }}" required />
                        <x-input-error :messages="$errors->get('name')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="cat_type" value="Type" />
                        <select id="cat_type" name="type"
                                class="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500 text-sm">
                            <option value="expense" {{ old('type') === 'expense' ? 'selected' : '' }}>Expense</option>
                            <option value="income"  {{ old('type') === 'income'  ? 'selected' : '' }}>Income</option>
                        </select>
                        <x-input-error :messages="$errors->get('type')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="icon" value="Icon (emoji)" />
                        <x-text-input id="icon" name="icon" type="text" maxlength="10"
                                      class="mt-1 block w-full" value="{{ old('icon') }}" placeholder="🏷️" />
                        <x-input-error :messages="$errors->get('icon')" class="mt-1" />
                    </div>

                    <div>
                        <x-input-label for="cat_color" value="Color" />
                        <div class="mt-1 flex items-center gap-2">
                            <input id="cat_color" name="color" type="color"
                                   class="h-9 w-12 border border-gray-300 rounded cursor-pointer"
                                   value="{{ old('color', '#6B7280') }}" />
                            <x-primary-button type="submit">Add</x-primary-button>
                        </div>
                        <x-input-error :messages="$errors->get('color')" class="mt-1" />
                    </div>

                </form>
            </div>

        </div>
    </div>
</x-app-layout>
